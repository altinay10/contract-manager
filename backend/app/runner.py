"""Analiz orkestratoru — checkpoint'li ve kaldigi yerden devam edebilen hat.

FAILSAFE TASARIMI
-----------------
1. ASAMA CHECKPOINT'I : Her asamanin durumu `stage_checkpoints` satirinda kalicidir.
   DONE olan asama yeniden calistirilmaz. Surec cokerse ayni contract icin yeniden
   baslatildiginda yalnizca PENDING/FAILED asamalar calisir.

2. IS PARCASI CHECKPOINT'I : Risk analizi madde madde ilerler ve her maddenin sonucu
   `work_items` tablosuna ayri satir olarak yazilir. 62 maddenin 40'inda cokerse,
   devam ettiginde yalnizca kalan 22 madde islenir. Pahali olan kisim budur.

3. YENIDEN DENEME : Her asama icin ustel beklemeli deneme hakki vardir. Hak bitince
   asama FAILED olur ama ONCEKI ASAMALARIN CIKTISI KORUNUR.

4. KALP ATISI : Calisan run `heartbeat_at` gunceller. Uygulama acilisinda kalp atisi
   bayatlamis (orphan) run'lar tespit edilip otomatik devam ettirilir.

5. IDEMPOTENSI : Her asama kendi ciktisini once temizler, sonra yazar. Yarim kalmis
   bir asamanin tekrari mukerrer kayit uretmez.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import commit_retry, read_session, session_scope
from .llm.budget import Budget, BudgetExceeded
from .llm.provider import (HeuristicProvider, LLMProvider, active_model,
                            get_provider)
from .models import (
    STAGE_KEYS, AnalysisRun, Clause, Contract, DroppedFinding, Finding, LLMCall,
    Report, StageCheckpoint, WorkItem, utcnow,
)
from .pipeline import gaps as gaps_mod
from .pipeline import report as report_mod
from .pipeline.analyze import FindingDraft, analyze_clause, dedupe
from .pipeline.classify import classify, yaygin_anahtarlar
from .pipeline.extract import ExtractionError, extract_ex
from .pipeline.meta import extract_meta
from .pipeline.normalize import normalize
from .pipeline.parties import alici_deseni, taraflari_ayir
from .pipeline.redlines import missing_annex_refs, taslak_kusurlari
from .pipeline.scoring import contract_score, finding_score
from .pipeline.segment import segment
from .pipeline.verify import ground, rebut
from .playbook.loader import load_playbook, mandatory_codes

log = logging.getLogger(__name__)

# Ilerleme/kalp atisi yazma araligi (sn). Arayuz iki saniyede bir yokluyor;
# madde basina yazmak dort es zamanli analizde SQLite'i kilitliyordu.
_BEAT_ARALIGI = 1.0

_active: dict[str, threading.Thread] = {}
_lock = threading.Lock()

# Bu surecin acilis kimligi. Yeniden baslatmada degisir; bu sayede "kim yurutuyordu?"
# sorusu zamandan bagimsiz cevaplanabilir.
BOOT_ID = uuid.uuid4().hex
_sweeper: threading.Thread | None = None
_sweeper_stop = threading.Event()


class StageError(RuntimeError):
    """Asama basarisiz — yeniden denenebilir."""


class FatalError(RuntimeError):
    """Yeniden denemenin anlami yok (bozuk dosya gibi)."""


class Cancelled(RuntimeError):
    """Kullanici analizi iptal etti."""


@dataclass
class Ctx:
    s: Session
    contract: Contract
    run: AnalysisRun
    cp: StageCheckpoint
    provider: LLMProvider
    budget: Budget | None = None
    _son_beat: float = 0.0

    @property
    def llm_active(self) -> bool:
        return self.provider.is_llm and (self.budget is None or self.budget.active)

    def check_cancel(self) -> None:
        """Isbirlikli iptal noktasi. Is parcacigi zorla oldurulmez; islem
        guvenli bir sinirda kendini durdurur ve o ana kadarki cikti korunur.

        AYRI OTURUM kullanilir: kosucunun oturumu acik bir islem icindeyse
        SQLite anlik goruntu yalitimi nedeniyle bayragi GORMEZ. `refresh()`
        bu durumda eski degeri dondurur ve iptal sessizce yok sayilir.
        """
        if iptal_istendi(self.run.contract_id):
            raise Cancelled("kullanıcı iptal etti")

    def beat(self, detail: str | None = None, done: int | None = None,
             total: int | None = None, zorla: bool = False) -> None:
        """Ilerleme ve kalp atisi yaz.

        KISILIR: madde basina yazmak, dort es zamanli analizde SQLite'i
        kilitlemeye yetiyordu (rapor asamasi uc denemesini de tuketip sozlesmeyi
        HATA'ya dusuruyordu). Arayuz zaten iki saniyede bir yokluyor; saniyede
        birden sik yazmanin kullaniciya faydasi yok. Asama sinirlarinda
        `zorla=True` ile kesin yazilir.

        Iptal denetimi de ayni ritme baglidir: iptal en fazla bir saniye
        gecikmeyle gorulur, arayuz zaten "islem guvenli bir noktada duracak"
        diyor.
        """
        self.run.heartbeat_at = utcnow()
        if detail is not None:
            self.cp.detail = detail[:300]
        if done is not None:
            self.cp.items_done = done
        if total is not None:
            self.cp.items_total = total

        simdi = time.monotonic()
        if not zorla and simdi - self._son_beat < _BEAT_ARALIGI:
            return
        self._son_beat = simdi
        commit_retry(self.s)
        self.check_cancel()

    def context_blocks(self) -> list[str]:
        """Model cagrilarinda onbelleklenen, sozlesme basina sabit baglam."""
        text = self.contract.normalized_text or ""
        return [
            "<sozlesme_tam_metni>\n" + text[:400000] + "\n</sozlesme_tam_metni>",
        ]


# --------------------------------------------------------------------------- #
# ASAMALAR
# --------------------------------------------------------------------------- #
def stage_ingest(ctx: Ctx) -> str:
    p = Path(ctx.contract.storage_path)
    if not p.exists():
        raise FatalError(f"Dosya bulunamadı: {p}")
    data = p.read_bytes()
    if not data:
        raise FatalError("Dosya boş")
    ctx.contract.sha256 = hashlib.sha256(data).hexdigest()
    ctx.contract.size_bytes = len(data)
    return f"{len(data)/1024:.0f} KB doğrulandı"


def stage_extract(ctx: Ctx) -> str:
    try:
        r = extract_ex(ctx.contract.storage_path)
    except ExtractionError as exc:
        raise FatalError(str(exc)) from exc
    ctx.contract.raw_text = r.text
    ctx.contract.page_map = r.pages

    meta = dict(ctx.contract.meta_json or {})
    meta["ocr_used"] = r.ocr_used
    meta["extract_note"] = r.note
    if r.ocr_confidence is not None:
        meta["ocr_confidence"] = r.ocr_confidence
    ctx.contract.meta_json = meta

    mesaj = f"{len(r.text):,} karakter, {len(r.pages)} sayfa"
    if r.ocr_used:
        mesaj += " · OCR"
        if r.ocr_confidence is not None:
            mesaj += f" (güven %{r.ocr_confidence:.0f})"
    return mesaj


def stage_normalize(ctx: Ctx) -> str:
    before = len(ctx.contract.raw_text or "")
    ctx.contract.normalized_text = normalize(ctx.contract.raw_text or "")
    after = len(ctx.contract.normalized_text)
    return f"{before:,} -> {after:,} karakter"


def stage_segment(ctx: Ctx) -> str:
    text = ctx.contract.normalized_text or ""
    if len(text) < 200:
        raise FatalError("Normalize metin çok kısa; belge okunamadı")
    clauses = segment(text)
    if not clauses:
        raise FatalError("Metinde madde tespit edilemedi")

    # Segmentasyon analiz BIRIMLERINI yeniden tanimlar. Bu yuzden maddelerden
    # tureyen her sey burada gecersizlesir: bulgular ve madde bazli is parcalari.
    # Aksi halde yeni bir calistirmada eski bulgular silinmeden yenileri eklenir
    # ve rapor mukerrer bulgularla sisir.
    cid = ctx.contract.id
    ctx.s.execute(delete(Clause).where(Clause.contract_id == cid))
    ctx.s.execute(delete(Finding).where(Finding.contract_id == cid))
    ctx.s.execute(delete(DroppedFinding).where(DroppedFinding.contract_id == cid))
    ctx.s.execute(
        delete(WorkItem).where(WorkItem.contract_id == cid, WorkItem.stage.in_(["RISK", "REBUT"]))
    )
    ctx.s.flush()
    for c in clauses:
        ctx.s.add(
            Clause(
                contract_id=ctx.contract.id,
                number=c.number, heading=c.heading, text=c.text,
                level=c.level, order_index=c.order_index,
                char_start=c.char_start, char_end=c.char_end,
            )
        )
    kinds = {c.kind for c in clauses}
    warn = " (başlık bulunamadı, paragraf modu)" if kinds == {"paragraf"} else ""
    return f"{len(clauses)} madde{warn}"


def stage_meta(ctx: Ctx) -> str:
    meta = dict(ctx.contract.meta_json or {})   # EXTRACT'in yazdigi OCR bilgisi korunur
    meta.update(extract_meta(ctx.contract.normalized_text or ""))
    alicilar, _ted = taraflari_ayir(ctx.contract.normalized_text or "")
    if alicilar:
        meta["alici"] = alicilar[0]
    ctx.contract.meta_json = meta
    ctx.contract.counterparty = meta.get("counterparty", "")
    ctx.contract.value_text = meta.get("value_text", "")
    ctx.contract.term_text = meta.get("term_text", "")
    return f"{meta.get('counterparty') or 'taraf bulunamadı'} · {meta.get('value_text') or '-'}"


def stage_classify(ctx: Ctx) -> str:
    clauses = _clauses(ctx)
    ctx.beat(total=len(clauses), done=0)

    # Belge genelinde cok gecen anahtarlar taraf adi/tanimli terimdir; agirliklari kirilir.
    yaygin = yaygin_anahtarlar([(c.heading or "", c.text or "") for c in clauses],
                               ctx.contract.contract_type)
    alici = alici_deseni(ctx.contract.normalized_text or "")
    alicilar, tedarikciler = taraflari_ayir(ctx.contract.normalized_text or "")
    if alicilar:
        log.info("Alıcı taraf: %s | tedarikçi: %s",
                 ", ".join(alicilar), ", ".join(tedarikciler) or "—")
    if yaygin:
        log.info("Tanımlı terim sayılan anahtar: %s", ", ".join(sorted(yaygin))[:200])

    matched = 0
    for i, cl in enumerate(clauses, 1):
        cl.codes = classify(cl.heading, cl.text, ctx.contract.contract_type, yaygin, alici)
        if cl.codes:
            matched += 1
        if i % 10 == 0:
            ctx.beat(detail=f"madde {i} / {len(clauses)}", done=i)
    ctx.beat(detail=f"madde {len(clauses)} / {len(clauses)}", done=len(clauses))
    return f"{matched}/{len(clauses)} madde eşleşti"


def stage_deterministic(ctx: Ctx) -> str:
    """Ucuz ve isabetli kontroller. Bulgu uretir ve modele hedef gosterir."""
    _clear_findings(ctx, detected_by="RULE_DET")
    text = ctx.contract.normalized_text or ""
    n = 0

    # --- taslak kusurlari: eksik ozne, doldurulmamis bosluk ---
    for kusur in taslak_kusurlari(text):
        _add_finding(
            ctx,
            FindingDraft(
                code="ENTIRE_AGREEMENT",
                clause_number="",
                finding_type="DRAFTING_DEFECT",
                severity=kusur["severity"],
                title=kusur["title"],
                rationale=kusur["rationale"],
                quote=kusur["quote"],
                confidence=0.95,
                detected_by="RULE_DET",
            ),
        )
        n += 1

    for ref in missing_annex_refs(text):
        _add_finding(
            ctx,
            FindingDraft(
                # Eklere atif ve ekler hiyerarsisi bu madde tipinin konusudur.
                code="ENTIRE_AGREEMENT",
                clause_number="",
                finding_type="CROSS_REF_ERROR",
                severity="ORTA",
                title=f"Metinde EK-{ref}'e atıf var ancak bu ek sözleşmede bulunamadı",
                rationale=(
                    f"Sözleşme EK-{ref}'e atıf yapıyor fakat belgede bu ek başlığı yok. "
                    "Atıf yapılan ekin içeriği belirsizse madde uygulanamaz hâle gelir."
                ),
                quote="",
                confidence=0.9,
                detected_by="RULE_DET",
            ),
        )
        n += 1
    return f"{n} taslak/atıf sorunu" if n else "sorun bulunamadı"


def stage_risk(ctx: Ctx) -> str:
    """En pahali asama — madde basina checkpoint'li ilerler."""
    pb = load_playbook()
    clauses = [c for c in _clauses(ctx) if c.codes]
    total = len(clauses)
    ctx.beat(total=total, done=0)

    def item_key_of(cl: Clause) -> str:
        """Kalici madde anahtari. uuid kullanilmaz: yeniden segmentasyonda degisir."""
        return f"{cl.order_index}:{cl.number}"

    done_keys = {
        w.item_key
        for w in ctx.s.scalars(
            select(WorkItem).where(
                WorkItem.contract_id == ctx.contract.id,
                WorkItem.stage == "RISK",
                WorkItem.status == "DONE",
            )
        )
    }
    if done_keys:
        log.info("RISK: %d madde onceki denemede tamamlanmis, atlaniyor", len(done_keys))

    context_blocks = ctx.context_blocks() if ctx.llm_active else []
    processed = len(done_keys)
    failed = 0

    # Yokluk kurallari icin kod bazli kapsam: ayni madde tipine ait tum maddelerin
    # birlesik metni. "Bu koruma sozlesmede hic yok mu?" sorusu ancak boyle sorulabilir.
    scope_by_code: dict[str, str] = {}
    first_clause_of_code: dict[str, str] = {}
    for cl in clauses:
        for cc in cl.codes or []:
            code = cc["code"]
            scope_by_code[code] = (scope_by_code.get(code, "") + "\n" + cl.text).strip()
            first_clause_of_code.setdefault(code, cl.id)

    # Kural desenlerindeki {ALICI} yer tutucusu bu sozlesmenin alici tarafiyla doldurulur.
    alici = alici_deseni(ctx.contract.normalized_text or "")
    taraflar = taraflari_ayir(ctx.contract.normalized_text or "")

    # MALIYET KONTROLU: modele yalnizca en agir maddeler gonderilir; geri kalani
    # kural katmaniyla islenir. Dikkat butcesinin (K6) mantiksal sonucu budur.
    llm_clause_ids: set[str] = set()
    if ctx.llm_active:
        def agirlik(cl: Clause) -> int:
            return max((pb[c["code"]].weight for c in (cl.codes or []) if c["code"] in pb),
                       default=0)

        siralı = sorted(clauses, key=lambda c: (-agirlik(c), c.order_index))
        limit = settings.max_llm_clauses or len(siralı)
        llm_clause_ids = {c.id for c in siralı[:limit]}
        if len(clauses) > len(llm_clause_ids):
            log.info(
                "RISK: %d maddeden %d tanesi modele gonderilecek (agirliga gore), "
                "kalani kural katmaniyla islenecek",
                len(clauses), len(llm_clause_ids),
            )

    for cl in clauses:
        ctx.check_cancel()
        key = item_key_of(cl)
        if key in done_keys:
            continue

        item = _get_item(ctx, "RISK", key)
        if item.attempts >= settings.item_max_attempts:
            failed += 1
            continue
        item.attempts += 1
        commit_retry(ctx.s)

        try:
            drafts: list[FindingDraft] = []
            for cc in cl.codes or []:
                ct = pb.get(cc["code"])
                if not ct:
                    continue
                d, comps = analyze_clause(
                    ctx.provider, cl.number, cl.heading, cl.text, ct, context_blocks,
                    scope_text=scope_by_code.get(cc["code"]),
                    # Yokluk kurali yalnizca o kodun ilk maddesinde uretilir -> mukerrer yok
                    include_absence=(first_clause_of_code.get(cc["code"]) == cl.id),
                    budget=ctx.budget,
                    use_llm=(cl.id in llm_clause_ids),
                    alici=alici,
                    taraflar=taraflar,
                )
                for x in d:
                    x.clause_id = cl.id
                drafts.extend(d)
                for comp in comps:
                    _log_call(ctx, "RiskAnalyst", comp)

            drafts = dedupe(drafts)
            # Bu maddenin onceki (yarim kalmis) bulgulari temizlenir -> idempotensi
            _clear_findings(ctx, clause_id=cl.id)
            for d in drafts:
                _add_finding(ctx, d)

            item.status = "DONE"
            item.result = {"findings": len(drafts)}
            item.error = ""
        except Exception as exc:  # tek madde tum analizi durdurmaz
            item.status = "FAILED"
            item.error = f"{type(exc).__name__}: {exc}"[:500]
            failed += 1
            log.warning("RISK madde %s basarisiz: %s", cl.number, exc)

        processed += 1
        commit_retry(ctx.s)
        if processed % 3 == 0 or processed == total:
            ctx.beat(detail=f"madde {processed} / {total}", done=processed)

    ctx.beat(detail=f"madde {total} / {total}", done=total)
    msg = f"{total} madde işlendi"
    if ctx.provider.is_llm:
        msg += f" ({len(llm_clause_ids)} tanesi modelle)"
    if failed:
        msg += f", {failed} madde başarısız"
    if ctx.budget and ctx.budget.disabled_reason:
        msg += f" — model kapatıldı: {ctx.budget.disabled_reason}"
    return msg


def stage_verify(ctx: Ctx) -> str:
    """Grounding (kod) + K7 karsi-gorus (model). Bulgu silme yetkisi yalnizca grounding'te."""
    findings = list(ctx.s.scalars(select(Finding).where(Finding.contract_id == ctx.contract.id)))
    clauses = {c.number: c.text for c in _clauses(ctx)}
    full = ctx.contract.normalized_text or ""

    drafts = [_to_draft(f) for f in findings]
    kept, dropped = ground(drafts, clauses, full)
    kept_titles = {(d.clause_number, d.code, d.title) for d in kept}

    removed = 0
    for f, d in zip(findings, drafts):
        if (d.clause_number, d.code, d.title) not in kept_titles:
            ctx.s.add(
                DroppedFinding(
                    contract_id=ctx.contract.id,
                    reason=next((r for dd, r in dropped if dd is d), "dogrulanamadi"),
                    payload=d.to_dict(),
                )
            )
            ctx.s.delete(f)
            removed += 1
        else:
            f.verified = True
    commit_retry(ctx.s)

    # K7 — yalnizca kritik/yuksek bulgularda, checkpoint'li
    rebutted = 0
    if ctx.llm_active:
        targets = list(
            ctx.s.scalars(
                select(Finding).where(
                    Finding.contract_id == ctx.contract.id,
                    Finding.severity.in_(["KRITIK", "YUKSEK"]),
                )
            )
        )
        ctx.beat(total=len(targets), done=0)
        clause_by_id = {c.id: c.text for c in _clauses(ctx)}
        cbs = ctx.context_blocks()
        for i, f in enumerate(targets, 1):
            item = _get_item(ctx, "REBUT", f.id)
            if item.status == "DONE":
                continue
            item.attempts += 1
            try:
                d = _to_draft(f)
                d2, comp = rebut(ctx.provider, d, clause_by_id.get(f.clause_id or "", ""),
                                 cbs, budget=ctx.budget)
                f.severity = d2.severity
                f.finding_type = d2.finding_type
                f.confidence = d2.confidence
                f.rebuttal = d2.rebuttal
                if comp:
                    _log_call(ctx, "Rebuttal", comp)
                item.status = "DONE"
                rebutted += 1
            except Exception as exc:
                item.status = "FAILED"
                item.error = str(exc)[:500]
            commit_retry(ctx.s)
            if i % 3 == 0:
                ctx.beat(detail=f"bulgu {i} / {len(targets)}", done=i)

    msg = f"{len(findings) - removed} bulgu doğrulandı"
    if removed:
        msg += f", {removed} bulgu düşürüldü"
    if rebutted:
        msg += f", {rebutted} karşı-görüş"
    return msg


def stage_report(ctx: Ctx) -> str:
    # K5 — eksik madde gecisi (yokluga dikkat)
    clauses = _clauses(ctx)
    detected = {cc["code"] for c in clauses for cc in (c.codes or [])}
    gap_drafts, comps = gaps_mod.detect_gaps(
        ctx.provider,
        ctx.contract.normalized_text or "",
        ctx.contract.contract_type,
        detected,
        ctx.context_blocks() if ctx.llm_active else [],
        budget=ctx.budget,
    )
    for comp in comps:
        _log_call(ctx, "GapAnalyst", comp)

    _clear_findings(ctx, finding_type="MISSING", only_gaps=True)
    for d in gap_drafts:
        _add_finding(ctx, d)
    commit_retry(ctx.s)

    findings = list(
        ctx.s.scalars(select(Finding).where(Finding.contract_id == ctx.contract.id))
    )
    payload_findings = [_finding_dict(f) for f in findings]
    score, band, veto = contract_score(
        payload_findings, ctx.contract.involves_personal_data, ctx.contract.is_outsourcing
    )
    ctx.contract.risk_score = score
    ctx.contract.risk_band = band
    ctx.contract.veto_reason = veto

    for f in findings:
        f.score = finding_score(
            f.code, f.severity, f.confidence,
            ctx.contract.involves_personal_data, ctx.contract.is_outsourcing,
        )

    sev_rank = {"KRITIK": 0, "YUKSEK": 1, "ORTA": 2, "DUSUK": 3, "BILGI": 4}
    payload_findings.sort(key=lambda f: (sev_rank.get(f["severity"], 9), -f.get("confidence", 0)))

    counts: dict[str, int] = {}
    for f in payload_findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    counts["MISSING"] = sum(1 for f in payload_findings if f["finding_type"] == "MISSING")

    # Basarisiz cagrilari da kayda gec: rapor sessiz kalmasin.
    if ctx.budget and ctx.budget.failures:
        kayitli = {
            (c.agent, c.error)
            for c in ctx.s.scalars(
                select(LLMCall).where(LLMCall.contract_id == ctx.contract.id, LLMCall.ok == False)  # noqa: E712
            )
        }
        for f in ctx.budget.failures:
            if (f["agent"], f["error"]) in kayitli:
                continue  # yeniden calistirmada mukerrer yazma
            ctx.s.add(LLMCall(
                contract_id=ctx.contract.id, agent=f["agent"],
                model=f["model"] or (active_model(ctx.provider) or ""),
                latency_ms=f["latency_ms"], ok=False, error=f["error"],
            ))
        ctx.s.flush()

    calls = list(ctx.s.scalars(select(LLMCall).where(LLMCall.contract_id == ctx.contract.id)))
    usage = usage_summary(calls)
    if ctx.budget:
        usage["budget_disabled_reason"] = ctx.budget.disabled_reason
        usage["attempted_calls"] = ctx.budget.calls
    dropped_n = ctx.s.query(DroppedFinding).filter(
        DroppedFinding.contract_id == ctx.contract.id
    ).count()

    # KAPSAM SEFFAFLIGI: hicbir madde tipine eslesmeyen maddeler analiz edilmedi.
    # Rapor bunu soylemezse okuyucu "her madde incelendi" sanir.
    incelenmeyen = [
        {"number": cl.number, "heading": cl.heading[:120],
         "preview": (cl.text or "").strip().replace("\n", " ")[:180]}
        for cl in clauses if not cl.codes
    ]

    payload = {
        "contract": {
            "id": ctx.contract.id,
            "filename": ctx.contract.filename,
            "counterparty": ctx.contract.counterparty,
            "contract_type": ctx.contract.contract_type,
            "value_text": ctx.contract.value_text,
            "term_text": ctx.contract.term_text,
            "clause_count": len(clauses),
            "risk_score": score,
            "risk_band": band,
            "veto_reason": veto,
            "meta": ctx.contract.meta_json or {},
        },
        "findings": payload_findings,
        "counts": counts,
        "generated_at": datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"),
        "engine": (
            f"{provider_label(ctx.provider)} + kural katmanı"
            if ctx.provider.is_llm
            else "kural tabanlı playbook motoru (model yapılandırılmamış)"
        ),
        "method": {
            "playbook_size": len(load_playbook()),
            "mandatory_count": len(mandatory_codes(ctx.contract.contract_type)),
            "dropped": dropped_n,
            "llm_calls": len(calls),
            "cost_usd": round(sum(c.cost_usd for c in calls), 4),
            "budget": ctx.budget.summary() if ctx.budget else None,
        },
        "usage": usage,
        "coverage": {
            "clauses_total": len(clauses),
            "clauses_classified": len(clauses) - len(incelenmeyen),
            "unreviewed": incelenmeyen,
        },
    }

    ctx.s.execute(delete(Report).where(Report.contract_id == ctx.contract.id))
    ctx.s.flush()
    for r in report_mod.build_reports(payload, ctx.contract.id):
        ctx.s.add(Report(contract_id=ctx.contract.id, **r))

    return f"skor {score} ({band}), {len(payload_findings)} bulgu, belge hazır"


STAGE_FUNCS = {
    "INGEST": stage_ingest,
    "EXTRACT": stage_extract,
    "NORMALIZE": stage_normalize,
    "SEGMENT": stage_segment,
    "META": stage_meta,
    "CLASSIFY": stage_classify,
    "DETERMINISTIC": stage_deterministic,
    "RISK": stage_risk,
    "VERIFY": stage_verify,
    "REPORT": stage_report,
}


# --------------------------------------------------------------------------- #
# YARDIMCILAR
# --------------------------------------------------------------------------- #
_HTTP_ACIKLAMA = {
    "400": "istek geçersiz", "401": "kimlik doğrulanamadı", "403": "erişim reddedildi",
    "404": "model bulunamadı", "429": "kota veya hız sınırı aşıldı",
    "500": "sağlayıcı hatası", "503": "sağlayıcı yoğunluğu",
}


def _hata_ozeti(ham: str) -> str:
    """Ham API cevabini kullaniciya gosterilecek tek satira indirger.

    Rapora bir JSON govdesi dusmemeli; "HTTP 429: kota veya hiz siniri asildi" yeterli.
    """
    if not ham:
        return ""
    m = re.match(r"HTTP (\d{3})", ham)
    if m:
        kod = m.group(1)
        return f"HTTP {kod}: {_HTTP_ACIKLAMA.get(kod, 'sağlayıcı hatası')}"
    return ham.split("\n")[0][:160]


def usage_summary(calls: list[LLMCall]) -> dict:
    """Token ve maliyet dokumu - rapordaki 'Model kullanimi' bolumunu besler."""
    # NULL'a dayanikli: sonradan eklenen kolonlar eski satirlarda bos olabilir.
    def top(alan: str) -> int:
        return sum(int(getattr(c, alan, 0) or 0) for c in calls)

    toplam = {
        "calls": len(calls),
        "input_tokens": top("input_tokens"),
        "output_tokens": top("output_tokens"),
        "cache_read_tokens": top("cache_read_tokens"),
        "cache_write_tokens": top("cache_write_tokens"),
        "cost_usd": round(sum(float(c.cost_usd or 0) for c in calls), 6),
        "latency_ms_total": top("latency_ms"),
        "failed": sum(1 for c in calls if not c.ok),
    }
    toplam["total_tokens"] = (
        toplam["input_tokens"] + toplam["output_tokens"] + toplam["cache_read_tokens"]
    )
    basarili = [c for c in calls if c.ok]
    toplam["succeeded"] = len(basarili)
    toplam["avg_latency_ms"] = (
        round(sum(int(c.latency_ms or 0) for c in basarili) / len(basarili))
        if basarili else 0
    )
    # Ilk basarisiz cagrinin sebebi - kullaniciya "neden model calismadi" der.
    ilk_hata = next((c.error for c in calls if not c.ok and c.error), "")
    toplam["first_error"] = _hata_ozeti(ilk_hata)

    # Maliyet gercekten hesaplanabildi mi? Rapor "0" ile "bilinmiyor"u karistirmamali.
    from .llm.provider import fiyat_bul
    modeller = {c.model for c in calls if c.model}
    toplam["cost_known"] = bool(modeller) and all(fiyat_bul(m) is not None for m in modeller)

    ajanlar: dict[str, dict] = {}
    for c in calls:
        a = ajanlar.setdefault(
            c.agent or "?",
            {"agent": c.agent or "?", "model": c.model, "calls": 0, "input_tokens": 0,
             "output_tokens": 0, "cache_read_tokens": 0, "cost_usd": 0.0, "latency_ms": 0,
             "failed": 0},
        )
        a["calls"] += 1
        if not c.ok:
            a["failed"] += 1
        a["input_tokens"] += int(c.input_tokens or 0)
        a["output_tokens"] += int(c.output_tokens or 0)
        a["cache_read_tokens"] += int(c.cache_read_tokens or 0)
        a["cost_usd"] += float(c.cost_usd or 0)
        a["latency_ms"] += int(c.latency_ms or 0)
    for a in ajanlar.values():
        a["cost_usd"] = round(a["cost_usd"], 6)
        a["avg_latency_ms"] = round(a["latency_ms"] / a["calls"]) if a["calls"] else 0

    toplam["by_agent"] = sorted(ajanlar.values(), key=lambda x: -x["cost_usd"])
    return toplam


def provider_label(provider: LLMProvider) -> str:
    ad = {"anthropic": "Claude", "gemini": "Gemini"}.get(provider.name, provider.name)
    m = active_model(provider)
    return f"{ad} ({m})" if m else ad


def _clauses(ctx: Ctx) -> list[Clause]:
    return list(
        ctx.s.scalars(
            select(Clause).where(Clause.contract_id == ctx.contract.id).order_by(Clause.order_index)
        )
    )


def _get_item(ctx: Ctx, stage: str, key: str) -> WorkItem:
    item = ctx.s.scalar(
        select(WorkItem).where(
            WorkItem.contract_id == ctx.contract.id,
            WorkItem.stage == stage,
            WorkItem.item_key == key,
        )
    )
    if item is None:
        item = WorkItem(contract_id=ctx.contract.id, stage=stage, item_key=key)
        ctx.s.add(item)
        ctx.s.flush()
    return item


def _clear_findings(ctx: Ctx, clause_id: str | None = None, detected_by: str | None = None,
                    finding_type: str | None = None, only_gaps: bool = False) -> None:
    q = delete(Finding).where(Finding.contract_id == ctx.contract.id)
    if clause_id is not None:
        q = q.where(Finding.clause_id == clause_id)
    if detected_by is not None:
        q = q.where(Finding.detected_by == detected_by)
    if finding_type is not None:
        q = q.where(Finding.finding_type == finding_type)
    if only_gaps:
        q = q.where(Finding.clause_number == "")
    ctx.s.execute(q)
    ctx.s.flush()


def _add_finding(ctx: Ctx, d: FindingDraft) -> None:
    ctx.s.add(
        Finding(
            contract_id=ctx.contract.id,
            clause_id=d.clause_id,
            code=d.code,
            clause_number=d.clause_number,
            finding_type=d.finding_type,
            severity=d.severity,
            title=d.title,
            rationale=d.rationale,
            quote=d.quote,
            quote_is_evidence=d.quote_is_evidence,
            legal_basis=d.legal_basis,
            proposed_text=d.proposed_text,
            negotiation_note=d.negotiation_note,
            confidence=d.confidence,
            detected_by=d.detected_by,
            lens=d.lens,
        )
    )


def _to_draft(f: Finding) -> FindingDraft:
    return FindingDraft(
        code=f.code, clause_number=f.clause_number, finding_type=f.finding_type,
        severity=f.severity, title=f.title, rationale=f.rationale, quote=f.quote,
        legal_basis=list(f.legal_basis or []), proposed_text=f.proposed_text,
        negotiation_note=f.negotiation_note, confidence=f.confidence,
        detected_by=f.detected_by, lens=f.lens, clause_id=f.clause_id,
        rebuttal=f.rebuttal or "",
        quote_is_evidence=bool(f.quote_is_evidence),
    )


def _finding_dict(f: Finding) -> dict:
    return {
        "id": f.id, "clause_number": f.clause_number, "code": f.code,
        "finding_type": f.finding_type, "severity": f.severity, "title": f.title,
        "rationale": f.rationale, "quote": f.quote,
        "quote_is_evidence": bool(f.quote_is_evidence),
        "legal_basis": list(f.legal_basis or []),
        "proposed_text": f.proposed_text, "negotiation_note": f.negotiation_note,
        "confidence": f.confidence, "detected_by": f.detected_by, "lens": f.lens,
        "rebuttal": f.rebuttal,
        "plain": (load_playbook().get(f.code).plain_tr if f.code in load_playbook() else ""),
        "clause_name": (load_playbook()[f.code].name_tr if f.code in load_playbook() else f.code),
    }


def _log_call(ctx: Ctx, agent: str, comp) -> None:
    u = comp.usage
    ctx.s.add(
        LLMCall(
            contract_id=ctx.contract.id, agent=agent, model=u.model,
            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_tokens, cache_write_tokens=u.cache_write_tokens,
            cost_usd=u.cost_usd, latency_ms=u.latency_ms, ok=u.ok, error=u.error,
        )
    )


# --------------------------------------------------------------------------- #
# CALISTIRICI
# --------------------------------------------------------------------------- #
def _get_or_create_run(s: Session, contract_id: str) -> AnalysisRun:
    run = s.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.contract_id == contract_id)
        .order_by(AnalysisRun.started_at.desc())
    )
    if run and run.status in ("PENDING", "RUNNING", "FAILED"):
        run.resumed_count += 1
        run.status = "RUNNING"
        run.error = ""
        run.owner_id = BOOT_ID
        run.heartbeat_at = utcnow()
        commit_retry(s)
        return run

    run = AnalysisRun(contract_id=contract_id, status="RUNNING", owner_id=BOOT_ID)
    s.add(run)
    s.flush()
    for pos, key in enumerate(STAGE_KEYS):
        s.add(StageCheckpoint(run_id=run.id, stage=key, position=pos))
    commit_retry(s)
    return run


def _checkpoint(s: Session, run: AnalysisRun, stage: str, pos: int) -> StageCheckpoint:
    cp = s.scalar(
        select(StageCheckpoint).where(
            StageCheckpoint.run_id == run.id, StageCheckpoint.stage == stage
        )
    )
    if cp is None:
        cp = StageCheckpoint(run_id=run.id, stage=stage, position=pos)
        s.add(cp)
        commit_retry(s)
    return cp


def execute(contract_id: str) -> None:
    """Analizi bastan ya da kaldigi yerden yurutur."""
    with session_scope() as s:
        contract = s.get(Contract, contract_id)
        if contract is None:
            log.error("Sozlesme bulunamadi: %s", contract_id)
            return

        # Sunucunun kendi LLM anahtari yalnizca giris yapmis kullanicilara ayrilir.
        # Parolasiz yuklenen sozlesmeler kural katmaniyla analiz edilir; boylece
        # uygulama herkese acik kalirken API kotasi korunur.
        if contract.model_izinli:
            provider = get_provider()
        else:
            provider = HeuristicProvider()
            log.info("Sozlesme %s parolasiz yuklendi; kural katmani kullaniliyor",
                     contract_id)
        # Butce her calistirmada sifirlanir; devam eden analiz yeni bir tavanla surer.
        budget = Budget() if provider.is_llm else None

        run = _get_or_create_run(s, contract_id)
        contract.status = "ISLENIYOR"
        commit_retry(s)

        resumed = [
            cp.stage
            for cp in s.scalars(
                select(StageCheckpoint).where(
                    StageCheckpoint.run_id == run.id, StageCheckpoint.status == "DONE"
                )
            )
        ]
        if resumed:
            log.info("Devam ediliyor: %d asama zaten tamam (%s)", len(resumed), ", ".join(resumed))

        for pos, stage in enumerate(STAGE_KEYS):
            cp = _checkpoint(s, run, stage, pos)
            if cp.status == "DONE":
                continue

            try:
                ctx_iptal = Ctx(s=s, contract=contract, run=run, cp=cp,
                                provider=provider, budget=budget)
                ctx_iptal.check_cancel()
            except Cancelled:
                _iptal_isaretle(s, run, contract)
                return

            run.current_stage = stage
            cp.status = "RUNNING"
            cp.started_at = cp.started_at or utcnow()
            run.heartbeat_at = utcnow()
            commit_retry(s)

            ctx = Ctx(s=s, contract=contract, run=run, cp=cp,
                      provider=provider, budget=budget)
            ctx.beat(zorla=True)      # asama basinda ilerleme kesin yazilir
            ok = False
            while cp.attempts < settings.stage_max_attempts:
                cp.attempts += 1
                commit_retry(s)
                try:
                    detail = STAGE_FUNCS[stage](ctx)
                    cp.status = "DONE"
                    cp.detail = (detail or "")[:300]
                    cp.error = ""
                    cp.finished_at = utcnow()
                    run.heartbeat_at = utcnow()
                    commit_retry(s)
                    log.info("[%s] %s — %s", contract_id[:8], stage, detail)
                    ok = True
                    break
                except Cancelled:
                    cp.status = "PENDING"
                    cp.detail = "iptal edildi"
                    commit_retry(s)
                    _iptal_isaretle(s, run, contract)
                    log.info("[%s] analiz iptal edildi (%s aşamasında)", contract_id[:8], stage)
                    return
                except FatalError as exc:
                    cp.status = "FAILED"
                    cp.error = str(exc)[:1000]
                    commit_retry(s)
                    log.error("[%s] %s olumcul hata: %s", contract_id[:8], stage, exc)
                    break
                except Exception as exc:
                    cp.error = f"{type(exc).__name__}: {exc}"[:1000]
                    s.rollback()
                    commit_retry(s)
                    log.warning(
                        "[%s] %s deneme %d/%d basarisiz: %s",
                        contract_id[:8], stage, cp.attempts, settings.stage_max_attempts, exc,
                    )
                    log.debug(traceback.format_exc())
                    if cp.attempts < settings.stage_max_attempts:
                        time.sleep(settings.retry_base_seconds * (2 ** (cp.attempts - 1)))
                    else:
                        cp.status = "FAILED"
                        commit_retry(s)

            if not ok:
                run.status = "FAILED"
                run.error = cp.error
                run.finished_at = utcnow()
                contract.status = "HATA"
                commit_retry(s)
                return

        run.status = "DONE"
        run.current_stage = ""
        run.finished_at = utcnow()
        contract.status = "TAMAMLANDI"
        commit_retry(s)
        if budget:
            b = budget.summary()
            log.info("[%s] analiz tamamlandi — %d model cagrisi, $%.4f, %d token%s",
                     contract_id[:8], b["calls"], b["cost_usd"], b["total_tokens"],
                     f" ({b['disabled_reason']})" if b["disabled_reason"] else "")
        else:
            log.info("[%s] analiz tamamlandi (kural tabanli)", contract_id[:8])


def _iptal_isaretle(s: Session, run: AnalysisRun, contract: Contract) -> None:
    run.status = "IPTAL"
    run.finished_at = utcnow()
    run.error = "Kullanıcı tarafından iptal edildi"
    contract.status = "IPTAL"
    commit_retry(s)


def iptal_istendi(contract_id: str) -> bool:
    """Iptal bayragini taze bir oturumdan okur (salt-okunur)."""
    with read_session() as s:
        run = s.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.contract_id == contract_id)
            .order_by(AnalysisRun.started_at.desc())
        )
        return bool(run and run.cancel_requested)


def cancel(contract_id: str) -> bool:
    """Iptal talebi birakir. Calisan islem bir sonraki guvenli noktada durur."""
    with session_scope() as s:
        run = s.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.contract_id == contract_id)
            .order_by(AnalysisRun.started_at.desc())
        )
        if run is None or run.status in ("DONE", "FAILED", "IPTAL"):
            return False
        run.cancel_requested = True
        commit_retry(s)
        return True


def start(contract_id: str) -> bool:
    """Analizi arka planda baslatir. Zaten calisiyorsa False doner."""
    with _lock:
        t = _active.get(contract_id)
        if t and t.is_alive():
            return False

        def _target():
            try:
                execute(contract_id)
            except Exception as exc:
                log.exception("Analiz thread'i beklenmedik sekilde sonlandi")
                # Isaretlenmezse sozlesme sonsuza dek "surüyor" kalir: arayuz
                # ilerleme cubugunda donar, kullanici devam da edemez. Hata
                # yazilirsa asama kontrol noktalari korunur ve "kaldigi yerden
                # devam et" calisir.
                _hata_isaretle(contract_id, exc)
            finally:
                with _lock:
                    _active.pop(contract_id, None)

        th = threading.Thread(target=_target, name=f"analiz-{contract_id[:8]}", daemon=True)
        _active[contract_id] = th
        th.start()
        return True


def _hata_isaretle(contract_id: str, exc: BaseException) -> None:
    """Beklenmedik cokme sonrasi sozlesmeyi HATA'ya cek (en iyi cabayla)."""
    try:
        with session_scope() as s:
            c = s.get(Contract, contract_id)
            if c is not None and c.status == "ISLENIYOR":
                c.status = "HATA"
            run = s.scalars(
                select(AnalysisRun).where(AnalysisRun.contract_id == contract_id)
                .order_by(AnalysisRun.started_at.desc())
            ).first()
            if run is not None and run.status == "RUNNING":
                run.status = "FAILED"
                run.error = f"beklenmedik hata: {exc}"[:1000]
    except Exception:            # veritabani da erisilemiyorsa yapacak bir sey yok
        log.exception("Cokme sonrasi durum yazilamadi")


def is_running(contract_id: str) -> bool:
    with _lock:
        t = _active.get(contract_id)
        return bool(t and t.is_alive())


def recover_orphans(start_work: bool = True) -> int:
    """Acilista: yarim kalmis run'lari kaldigi yerden devam ettir.

    Uygulama cokup yeniden ayaga kalktiginda yarim kalan analizler kaybolmaz.

    start_work=False: yalnizca oksuzleri isaretler, is parcacigi BASLATMAZ.
    Kuru calistirma ve testler icin; bir denetim komutundan da cagrilabilir.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.orphan_after_seconds)
    resumed = 0
    oksuz_ids: list[str] = []
    with session_scope() as s:
        runs = list(
            s.scalars(select(AnalysisRun).where(AnalysisRun.status.in_(["RUNNING", "PENDING"])))
        )
        for run in runs:
            if run.cancel_requested:
                continue  # iptal edilmis is dirilmemeli
            # Iki oksuzluk olcutu:
            #  1. Baska bir acilis tarafindan baslatilmis  -> kesin oksuz (zamandan bagimsiz)
            #  2. Bu acilisin isi ama kalp atisi bayatlamis -> is parcacigi olmus
            baska_acilis = (run.owner_id or "") != BOOT_ID
            hb = run.heartbeat_at
            if hb is not None and hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            bayat = hb is None or hb <= cutoff
            if not baska_acilis and not bayat:
                continue  # gercekten calisiyor, dokunma
            if not baska_acilis and is_running(run.contract_id):
                continue  # is parcacigi yasiyor
            for cp in s.scalars(
                select(StageCheckpoint).where(
                    StageCheckpoint.run_id == run.id, StageCheckpoint.status == "RUNNING"
                )
            ):
                cp.status = "PENDING"
                cp.detail = "kesinti sonrası yeniden denenecek"
            run.owner_id = BOOT_ID
            commit_retry(s)
            resumed += 1
            oksuz_ids.append(run.contract_id)
            log.warning(
                "Yarim kalmis analiz devam ettiriliyor: %s (%s)",
                run.contract_id[:8],
                "onceki acilis" if baska_acilis else "kalp atisi bayat",
            )

    if start_work:
        for cid in dict.fromkeys(oksuz_ids):
            start(cid)
    return resumed


def apply_retention() -> int:
    """Saklama suresi gecen sozlesmeleri SILINMIS olarak isaretler.

    RETENTION_DAYS=0 (varsayilan) ise hicbir sey yapmaz.

    Isaretleme YUMUSAKTIR ve bilincli olarak oyledir: hicbir satir
    veritabanindan dusurulmez, hicbir dosya diskten kaldirilmaz. Yalnizca
    `silindi_at` damgasi konur; sozlesme listelerden ve bulgu/rapor uclarindan
    kaybolur, ama `POST /api/contracts/{id}/restore` ile geri alinabilir.
    Otomatik bir islemin geri donusu olmayan silme yapmasi istenmez.

    Karsilastirma Python tarafinda yapilir: `created_at` SQLite'ta saat dilimsiz
    saklanir, tz-farkindali bir siniri dogrudan SQL'e bindirmek sessiz yanlis
    sonuc verir (bkz. recover_orphans'taki ayni normalizasyon).
    """
    gun = settings.retention_days
    if gun <= 0:
        return 0
    simdi = datetime.now(timezone.utc)
    cutoff = simdi - timedelta(days=gun)
    isaretlenen = 0
    with session_scope() as s:
        rows = list(s.scalars(select(Contract).where(Contract.silindi_at.is_(None))))
        for c in rows:
            olusma = c.created_at
            if olusma is None:
                continue
            if olusma.tzinfo is None:
                olusma = olusma.replace(tzinfo=timezone.utc)
            if olusma > cutoff:
                continue
            if is_running(c.id):
                continue            # suren analiz yarida kesilmesin
            c.silindi_at = simdi
            isaretlenen += 1
        if isaretlenen:
            s.commit()
            log.info(
                "Saklama suresi (%d gun): %d sozlesme silinmis olarak isaretlendi "
                "(veri silinmedi, geri alinabilir)", gun, isaretlenen,
            )
    return isaretlenen


def start_sweeper() -> None:
    """Periyodik oksuz tarayici.

    Acilistaki tek seferlik tarama, uygulama ayaktayken olen bir is parcacigini
    yakalayamaz. Bu tarayici o bosluğu kapatir.
    """
    global _sweeper
    if not settings.sweeper_enabled:
        log.info("Öksüz tarayıcı kapalı (SWEEPER_ENABLED=0)")
        return
    if _sweeper and _sweeper.is_alive():
        return

    _sweeper_stop.clear()

    def _dongu():
        aralik = max(30, settings.orphan_after_seconds // 2)
        # Event.wait: kapanma sinyalini beklerken uykuyu boler -> temiz kapanis.
        while not _sweeper_stop.wait(aralik):
            try:
                recover_orphans()
            except Exception:
                log.exception("Öksüz tarayıcı hatası")
            try:
                apply_retention()
            except Exception:
                log.exception("Saklama süresi taraması hatası")

    _sweeper = threading.Thread(target=_dongu, name="oksuz-tarayici", daemon=True)
    _sweeper.start()


def stop_sweeper() -> None:
    """Uygulama kapanirken tarayiciyi temiz durdurur."""
    _sweeper_stop.set()


def progress(contract_id: str) -> dict:
    """UI icin canli durum."""
    from .models import STAGE_LABEL

    with read_session() as s:
        contract = s.get(Contract, contract_id)
        # Silinmis sozlesme yok gibi davranir. Denetim BURADA yapilir: bu uc
        # arayuz tarafindan saniyede bir yoklanir, main.py'de ayri bir oturum
        # acmak ayni SQLite dosyasinda bosuna kilit cakismasi uretirdi.
        if contract is None or contract.silindi_at is not None:
            return {}
        run = s.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.contract_id == contract_id)
            .order_by(AnalysisRun.started_at.desc())
        )
        cps = {}
        if run:
            for cp in s.scalars(select(StageCheckpoint).where(StageCheckpoint.run_id == run.id)):
                cps[cp.stage] = cp

        stages = []
        for pos, key in enumerate(STAGE_KEYS):
            cp = cps.get(key)
            label, desc = STAGE_LABEL[key]
            stages.append(
                {
                    "key": key, "label": label, "desc": desc, "position": pos,
                    "status": cp.status if cp else "PENDING",
                    "detail": cp.detail if cp else "",
                    "attempts": cp.attempts if cp else 0,
                    "error": cp.error if cp else "",
                    "items_done": cp.items_done if cp else 0,
                    "items_total": cp.items_total if cp else 0,
                }
            )

        done = sum(1 for st in stages if st["status"] == "DONE")
        current = next((st for st in stages if st["status"] == "RUNNING"), None)
        pct = done / len(stages) * 100
        if current and current["items_total"]:
            pct += (current["items_done"] / current["items_total"]) * (100 / len(stages))

        reports = [
            {"fmt": r.fmt, "filename": r.filename, "size_bytes": r.size_bytes, "id": r.id}
            for r in s.scalars(select(Report).where(Report.contract_id == contract_id))
        ]

        return {
            "contract_id": contract_id,
            "status": contract.status,
            "filename": contract.filename,
            "counterparty": contract.counterparty,
            "value_text": contract.value_text,
            "term_text": contract.term_text,
            "risk_score": contract.risk_score,
            "risk_band": contract.risk_band,
            "veto_reason": contract.veto_reason,
            "stages": stages,
            "current_stage": current["key"] if current else (run.current_stage if run else ""),
            "percent": round(min(100.0, pct), 1),
            "resumed_count": run.resumed_count if run else 0,
            "cancel_requested": bool(run.cancel_requested) if run else False,
            "cancellable": bool(run and run.status in ("RUNNING", "PENDING")
                                and not run.cancel_requested),
            "run_status": run.status if run else "",
            "error": run.error if run else "",
            "reports": reports,
            "running": is_running(contract_id),
        }
