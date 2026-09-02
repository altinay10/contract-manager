"""Model yolunun ucretsiz testi + butce muhafizi testleri.

Amac: gercek API cagrisi yapmadan LLM kod yolunun tamamini calistirmak.
Canli denemeden once her seyin dogru oldugundan boyle emin oluruz.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import runner
from app.db import engine, session_scope
from app.llm.budget import Budget, BudgetExceeded
from app.llm.provider import (
    Completion, LLMError, LLMPermanentError, Turn, Usage, _parse_json, to_gemini_schema,
)
from app.models import Base, Contract, Finding, LLMCall

SAMPLE = Path(__file__).resolve().parent.parent.parent / "samples" / "ornek-saas-sozlesmesi.txt"


# --------------------------------------------------------------- butce
def test_cagri_tavani_asilinca_model_kapanir():
    b = Budget(max_calls=2, max_cost_usd=99, max_total_tokens=10**9)
    for _ in range(2):
        b.check()
        b.record_success(0.001, 100)
    with pytest.raises(BudgetExceeded, match="tavanı doldu"):
        b.check()
    assert not b.active


def test_maliyet_tavani_asilinca_model_kapanir():
    b = Budget(max_calls=100, max_cost_usd=0.05)
    b.check()
    b.record_success(0.06, 100)
    with pytest.raises(BudgetExceeded, match="maliyet"):
        b.check()


def test_token_tavani_asilinca_model_kapanir():
    b = Budget(max_calls=100, max_cost_usd=99, max_total_tokens=500)
    b.check()
    b.record_success(0.0, 600)
    with pytest.raises(BudgetExceeded, match="token"):
        b.check()


def test_ust_uste_hata_devreyi_keser():
    b = Budget(max_consecutive_failures=2)
    b.check(); b.record_failure()
    b.check(); b.record_failure()
    with pytest.raises(BudgetExceeded, match="devre kesildi"):
        b.check()


def test_basarili_cagri_hata_sayacini_sifirlar():
    b = Budget(max_consecutive_failures=2)
    b.check(); b.record_failure()
    b.check(); b.record_success(0.0, 10)
    b.check(); b.record_failure()
    b.check()  # devre acilmamali
    assert b.active


def test_kalici_hata_modeli_hemen_kapatir():
    b = Budget(max_consecutive_failures=10)
    b.check()
    b.record_failure(permanent=True, reason="gecersiz anahtar")
    with pytest.raises(BudgetExceeded, match="gecersiz anahtar"):
        b.check()


def test_sure_tavani():
    b = Budget(deadline_seconds=0)
    with pytest.raises(BudgetExceeded, match="süre tavanı"):
        b.check()


# --------------------------------------------------------------- gemini
def test_gemini_sema_donusumu():
    g = to_gemini_schema({
        "type": "object",
        "properties": {"a": {"type": "string", "enum": ["X"]},
                       "b": {"type": "array", "items": {"type": "number"}}},
        "required": ["a"],
        "additionalProperties": False,
    })
    assert g["type"] == "OBJECT"
    assert g["properties"]["a"]["type"] == "STRING"
    assert g["properties"]["a"]["enum"] == ["X"]
    assert g["properties"]["b"]["items"]["type"] == "NUMBER"
    assert "additionalProperties" not in json.dumps(g)
    assert g["required"] == ["a"]


def test_kod_blogu_sarilmis_json_ayristirilir():
    assert _parse_json('```json\n{"x": 1}\n```') == {"x": 1}
    assert _parse_json('{"x": 2}') == {"x": 2}
    with pytest.raises(LLMError):
        _parse_json("bu JSON değil")
    with pytest.raises(LLMError):
        _parse_json("")


# --------------------------------------------------------------- sahte model
class SahteSaglayici:
    """Sema uyumlu, metne dayali cevap ureten sahte model.

    Alintiyi GERCEK madde metninden alir; boylece grounding katmani da test edilir.
    """

    name = "sahte"
    is_llm = True

    def __init__(self, mod: str = "normal"):
        self.mod = mod
        self.cagri = 0
        self.gorulen_promptlar: list[str] = []

    def complete_json(self, turn: Turn, budget: Budget | None = None) -> Completion:
        if budget is not None:
            budget.check()
        self.cagri += 1
        self.gorulen_promptlar.append(turn.task_block)

        if self.mod == "hep_hata":
            if budget is not None:
                budget.record_failure()
            raise LLMError("simüle edilmiş geçici hata")

        data = self._cevap(turn)
        usage = Usage(model="sahte-model", input_tokens=1000, output_tokens=200, cost_usd=0.001)
        if budget is not None:
            budget.record_success(usage.cost_usd, usage.total)
        return Completion(data=data, usage=usage)

    def _cevap(self, turn: Turn) -> dict:
        if "CURUTULECEK BULGU" in turn.task_block:
            return {"verdict": "ABARTILI", "rebuttal": "Madde bağlamında risk sınırlıdır.",
                    "suggested_severity": "ORTA"}
        if "ARANACAK ZORUNLU KORUMALAR" in turn.task_block:
            return {"results": []}

        # Risk analizi: madde metninden gercek bir alinti sec
        govde = ""
        if "<madde_metni>" in turn.task_block:
            govde = turn.task_block.split("<madde_metni>")[1].split("</madde_metni>")[0].strip()
        cumleler = [c.strip() for c in govde.split(".") if len(c.strip()) > 40]
        if not cumleler:
            return {"findings": [], "injection_attempt": False}

        alinti = cumleler[0]
        if self.mod == "uydurma":
            alinti = "Bu cümle sözleşmede kesinlikle geçmiyor, model uydurdu."

        dayanaklar = []
        if "IZIN VERILEN DAYANAKLAR" in turn.task_block:
            blok = turn.task_block.split("IZIN VERILEN DAYANAKLAR")[1]
            dayanaklar = [s[2:].strip() for s in blok.split("\n") if s.startswith("- ")][:1]
        if self.mod == "uydurma_dayanak":
            dayanaklar = ["Uydurma Kanun m.999"]

        return {
            "findings": [{
                "finding_type": "WEAK", "severity": "YUKSEK",
                "title": "Sahte model bulgusu",
                "rationale": "Test amaçlı üretilmiş gerekçe.",
                "quote": alinti,
                "legal_basis": dayanaklar,
                "proposed_text": "Önerilen alternatif madde metni.",
                "negotiation_note": "Müzakere notu.",
                "confidence": 0.9,
            }],
            "injection_attempt": False,
        }


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(engine)
    yield


def _sozlesme() -> str:
    with session_scope() as s:
        # model_izinli: bu testler LLM yolunu dogruluyor; giris yapmis bir
        # kullanicinin yukledigi sozlesmeyi temsil eder.
        c = Contract(title="t", filename=SAMPLE.name, storage_path=str(SAMPLE),
                     contract_type="SAAS", involves_personal_data=True,
                     model_izinli=True)
        s.add(c); s.flush()
        return c.id


def _kos(monkeypatch, saglayici, **ayar) -> str:
    from app.config import settings
    for k, v in ayar.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(runner, "get_provider", lambda: saglayici)
    cid = _sozlesme()
    runner.execute(cid)
    return cid


def test_model_yolu_uctan_uca_calisir(monkeypatch):
    """Gercek API olmadan LLM dalinin tamami kosulur."""
    sag = SahteSaglayici()
    cid = _kos(monkeypatch, sag, max_llm_clauses=5, enable_lenses=False, enable_rebuttal=True)

    p = runner.progress(cid)
    assert p["run_status"] == "DONE"
    assert sag.cagri > 0, "model hiç çağrılmadı"

    with session_scope() as s:
        bulgular = list(s.scalars(select(Finding).where(Finding.contract_id == cid)))
        cagrilar = list(s.scalars(select(LLMCall).where(LLMCall.contract_id == cid)))

    assert any(f.detected_by == "LLM" for f in bulgular), "model bulgusu kaydedilmedi"
    assert cagrilar, "model çağrıları loglanmadı"
    assert all(c.cost_usd >= 0 for c in cagrilar)


def test_k2_kirmizi_cizgi_kontrol_listesi_prompta_zerk_ediliyor(monkeypatch):
    sag = SahteSaglayici()
    _kos(monkeypatch, sag, max_llm_clauses=8, enable_lenses=False, enable_rebuttal=False)
    birlesik = "\n".join(sag.gorulen_promptlar)
    assert "KIRMIZI CIZGI KONTROL LISTESI" in birlesik
    assert "KARSILANDI / IHLAL / METINDE YOK" in birlesik
    assert "<madde_metni>" in birlesik


UYDURMA_METIN = "Bu cümle sözleşmede kesinlikle geçmiyor"


def test_uydurma_alinti_rapora_giremez(monkeypatch):
    """Model uydurma alinti verirse bulgu DUSER - grounding katmani.

    Not: alintisi olmayan bulgular (eksik madde) tanimi geregi metne dayanmaz ve
    dusurulmez; test yalnizca UYDURMA ALINTILI bulgulari kontrol eder.
    """
    from app.models import DroppedFinding

    sag = SahteSaglayici(mod="uydurma")
    cid = _kos(monkeypatch, sag, max_llm_clauses=5, enable_lenses=False, enable_rebuttal=False)

    with session_scope() as s:
        bulgular = list(s.scalars(select(Finding).where(Finding.contract_id == cid)))
        dusenler = list(s.scalars(select(DroppedFinding).where(DroppedFinding.contract_id == cid)))

    alintili = [f for f in bulgular if f.quote]
    assert all(UYDURMA_METIN not in (f.quote or "") for f in alintili), \
        "uydurma alıntılı bulgu rapora girdi"
    assert dusenler, "uydurma bulgular düşürülmedi (grounding çalışmıyor)"
    assert all("bulunamadi" in d.reason for d in dusenler)


def test_uydurma_alintili_bulgu_sessizce_yutulmaz(monkeypatch):
    """Dusen bulgu kaydedilmeli: eval icin altin veri, ayrica denetlenebilirlik."""
    from app.models import DroppedFinding

    sag = SahteSaglayici(mod="uydurma")
    cid = _kos(monkeypatch, sag, max_llm_clauses=5, enable_lenses=False, enable_rebuttal=False)
    with session_scope() as s:
        payloads = [d.payload for d in
                    s.scalars(select(DroppedFinding).where(DroppedFinding.contract_id == cid))]
    assert any(UYDURMA_METIN in (pl or {}).get("quote", "") for pl in payloads)


def test_uydurma_mevzuat_dayanagi_temizlenir(monkeypatch):
    sag = SahteSaglayici(mod="uydurma_dayanak")
    cid = _kos(monkeypatch, sag, max_llm_clauses=5, enable_lenses=False, enable_rebuttal=False)
    with session_scope() as s:
        for f in s.scalars(select(Finding).where(Finding.contract_id == cid)):
            assert "Uydurma Kanun" not in json.dumps(f.legal_basis or [])


def test_butce_dolunca_analiz_cokmez_kural_katmani_devam_eder(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "max_llm_calls", 3)
    sag = SahteSaglayici()
    cid = _kos(monkeypatch, sag, max_llm_clauses=0, enable_lenses=False, enable_rebuttal=False)

    p = runner.progress(cid)
    assert p["run_status"] == "DONE", "bütçe dolunca analiz çökmemeli"
    assert sag.cagri <= 4, f"tavan aşıldı: {sag.cagri} çağrı"
    with session_scope() as s:
        n = s.query(Finding).filter(Finding.contract_id == cid).count()
    assert n > 0, "bütçe dolunca hiç bulgu üretilmemiş"


def test_model_surekli_hata_verirse_devre_kesilir_ve_analiz_tamamlanir(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "max_consecutive_failures", 2)
    sag = SahteSaglayici(mod="hep_hata")
    cid = _kos(monkeypatch, sag, max_llm_clauses=0, enable_lenses=False, enable_rebuttal=False)

    p = runner.progress(cid)
    assert p["run_status"] == "DONE"
    assert sag.cagri <= 4, f"devre kesilmedi, {sag.cagri} kez denendi"
    with session_scope() as s:
        assert s.query(Finding).filter(Finding.contract_id == cid).count() > 0


def test_madde_siniri_modele_giden_cagriyi_kisitlar(monkeypatch):
    sag = SahteSaglayici()
    _kos(monkeypatch, sag, max_llm_clauses=3, enable_lenses=False, enable_rebuttal=False)
    # 3 madde + eksik madde gecisi (1) -> en fazla 4 civari
    assert sag.cagri <= 5, f"madde sınırı uygulanmadı: {sag.cagri} çağrı"


# --------------------------------------------------------------- redline
def test_redline_gercek_degisiklik_izleme_uretir(tmp_path):
    import zipfile

    from app.pipeline.redline import build_redline

    payload = {
        "contract": {"filename": "x.pdf", "counterparty": "Y Ltd."},
        "generated_at": "01.01.2026",
        "findings": [
            {"clause_number": "12.3", "code": "LIMITATION_OF_LIABILITY",
             "finding_type": "RED_LINE", "severity": "KRITIK", "title": "Tavan düşük",
             "quote": "üç (3) ayda ödenen bedeli aşamaz",
             "proposed_text": "on iki (12) ayda ödenen bedeli aşamaz",
             "rationale": "gerekçe", "legal_basis": ["TBK m.115"], "negotiation_note": "not"},
            {"clause_number": "", "code": "SOURCE_CODE_ESCROW", "finding_type": "MISSING",
             "severity": "YUKSEK", "title": "Escrow yok", "quote": "",
             "proposed_text": "Tedarikçi kaynak kodunu emanet eder.",
             "rationale": "gerekçe", "legal_basis": [], "negotiation_note": ""},
        ],
    }
    yol = build_redline(payload, tmp_path / "r.docx")
    xml = zipfile.ZipFile(yol).read("word/document.xml").decode("utf-8")
    assert xml.count("<w:ins ") >= 2, "ekleme işareti yok"
    assert xml.count("<w:del ") >= 1, "silme işareti yok"
    assert "<w:delText" in xml


def test_pdf_metin_cikarimi_turkce_korur():
    from app.pipeline.extract import extract

    pdf = SAMPLE.with_suffix(".pdf")
    if not pdf.exists():
        pytest.skip("PDF örneği üretilmemiş (samples/pdf_uret.py)")
    metin, sayfalar = extract(pdf)
    assert len(sayfalar) <= 5, "örnek PDF 5 sayfayı aşmamalı"
    assert "Sözleşme" in metin
    assert "Tedarikçi" in metin


def test_saglik_ucu_aktif_modeli_bildirir(monkeypatch):
    """Gemini kullanilirken Claude modeli raporlanmamali."""
    from app.config import settings
    from app.llm import provider as prov

    monkeypatch.setattr(settings, "model_gemini", "gemini-flash-latest")
    monkeypatch.setattr(settings, "model_main", "claude-opus-5")

    class G:
        name = "gemini"; is_llm = True
    class A:
        name = "anthropic"; is_llm = True
    class H:
        name = "heuristic"; is_llm = False

    assert prov.active_model(G()) == "gemini-flash-latest"
    assert prov.active_model(A()) == "claude-opus-5"
    assert prov.active_model(H()) is None


def test_karsi_gorus_kapaliyken_is_parcasi_basarisiz_olmaz(monkeypatch):
    """ENABLE_REBUTTAL=0 iken rebut() erken doner; okuyan kod patlamamali.

    Gercek hata: FindingDraft'ta 'rebuttal' alani yoktu, 18 REBUT is parcasi
    AttributeError ile FAILED isaretleniyordu.
    """
    from app.models import WorkItem

    sag = SahteSaglayici()
    cid = _kos(monkeypatch, sag, max_llm_clauses=4, enable_lenses=False, enable_rebuttal=False)

    with session_scope() as s:
        basarisiz = [w for w in s.scalars(
            select(WorkItem).where(WorkItem.contract_id == cid, WorkItem.stage == "REBUT"))
            if w.status == "FAILED"]
    assert not basarisiz, f"karşı-görüş kapalıyken {len(basarisiz)} iş parçası başarısız oldu"


def test_karsi_gorus_acikken_gerekce_kaydedilir_ve_siddet_dusurulur(monkeypatch):
    """Sahte model 'ABARTILI' der; K7 bulguyu SILMEZ, yalnizca zayiflatir."""
    sag = SahteSaglayici()
    cid = _kos(monkeypatch, sag, max_llm_clauses=4, enable_lenses=False, enable_rebuttal=True)
    with session_scope() as s:
        llm_bulgular = [f for f in s.scalars(select(Finding).where(Finding.contract_id == cid))
                        if f.detected_by == "LLM" and f.quote]

    assert llm_bulgular, "model bulgusu yok"
    assert any(f.rebuttal for f in llm_bulgular), "karşı-görüş gerekçesi kaydedilmemiş"
    # Bulgu silinmedi, sadece siddeti dustu (YUKSEK -> ORTA)
    zayiflatilan = [f for f in llm_bulgular if f.rebuttal]
    assert all(f.severity == "ORTA" for f in zayiflatilan), \
        "karşı-görüş şiddeti düşürmedi"
    assert all(f.confidence < 0.9 for f in zayiflatilan), "güven düşürülmedi"


# --------------------------------------------------------------- şeffaflık
def test_basarisiz_cagrilar_kayda_gecer_ve_raporda_gorunur(monkeypatch, tmp_path):
    """Model denenip kapatildiysa rapor bunu SUSMAMALI.

    Gercek durum: Gemini 503 dondu, devre kesildi, analiz kural katmaniyla bitti -
    ama rapor hicbir sey soylemiyordu ve /usage "0 cagri" diyordu.
    """
    from app.config import settings
    from app.models import LLMCall
    from app.pipeline.report_html import build_html

    monkeypatch.setattr(settings, "max_consecutive_failures", 2)
    sag = SahteSaglayici(mod="hep_hata")
    cid = _kos(monkeypatch, sag, max_llm_clauses=6, enable_lenses=False, enable_rebuttal=False)

    with session_scope() as s:
        cagrilar = list(s.scalars(select(LLMCall).where(LLMCall.contract_id == cid)))
    assert cagrilar, "başarısız çağrılar hiç kaydedilmemiş"
    assert all(not c.ok for c in cagrilar)
    assert all(c.error for c in cagrilar), "hata mesajı kaydedilmemiş"

    ozet = runner.usage_summary(cagrilar)
    assert ozet["failed"] == len(cagrilar)
    assert ozet["succeeded"] == 0
    assert ozet["first_error"], "ilk hata sebebi taşınmamış"

    # Rapor bu durumu yaziyor mu?
    payload = {
        "contract": {"filename": "x.pdf", "risk_score": 40, "risk_band": "KIRMIZI",
                     "meta": {}, "clause_count": 10},
        "findings": [], "counts": {},
        "generated_at": "01.01.2026", "engine": "test",
        "method": {},
        "usage": {**ozet, "budget_disabled_reason": "üst üste 2 model hatası — devre kesildi"},
    }
    html = build_html(payload, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Model kullanımı" in html
    assert "Model devre dışı bırakıldı" in html
    assert "kural katmanıyla" in html


def test_basarili_analizde_kullanim_bolumu_dogru(monkeypatch, tmp_path):
    from app.models import LLMCall
    from app.pipeline.report_html import build_html

    sag = SahteSaglayici()
    cid = _kos(monkeypatch, sag, max_llm_clauses=4, enable_lenses=False, enable_rebuttal=False)
    with session_scope() as s:
        cagrilar = list(s.scalars(select(LLMCall).where(LLMCall.contract_id == cid)))

    ozet = runner.usage_summary(cagrilar)
    assert ozet["succeeded"] > 0
    assert ozet["input_tokens"] > 0 and ozet["output_tokens"] > 0
    assert ozet["total_tokens"] == (
        ozet["input_tokens"] + ozet["output_tokens"] + ozet["cache_read_tokens"]
    )
    assert ozet["by_agent"], "görev bazlı döküm yok"

    payload = {
        "contract": {"filename": "x.pdf", "risk_score": 40, "risk_band": "SARI",
                     "meta": {}, "clause_count": 10},
        "findings": [], "counts": {}, "generated_at": "01.01.2026",
        "engine": "test", "method": {}, "usage": ozet,
    }
    html = build_html(payload, tmp_path / "r2.html").read_text(encoding="utf-8")
    assert "Model kullanımı" in html
    assert 'class="bar"' in html, "token çubuğu çizilmemiş"
    assert "Girdi" in html and "Çıktı" in html


# --------------------------------------------------------------- prompt hijyeni
def test_sistem_promptu_taraf_adina_sabitlenmemis():
    """Gercek hata: prompt "Banka ALICI konumundadir" diyordu. Alici "PRATIK ISLEM"
    ise model yanlis taraf adiyla calisiyordu."""
    from app.pipeline.analyze import LENS_PROMPTS, SYSTEM_PROMPT

    assert "banka" not in SYSTEM_PROMPT.lower(), "sistem promptu hâlâ 'banka' diyor"
    assert "ALICI" in SYSTEM_PROMPT
    for ad, metin in LENS_PROMPTS.items():
        assert "banka" not in metin.lower(), f"{ad} merceği 'banka' diyor"


def test_gorev_blogu_gercek_taraf_adlarini_tasir():
    from app.pipeline.analyze import build_task_block
    from app.pipeline.redlines import evaluate_red_lines
    from app.playbook.loader import load_playbook

    ct = load_playbook()["STAMP_DUTY"]
    t = "Damga vergisi Pratik İşlem tarafından ödenir."
    tb = build_task_block("18", "MASRAFLAR", t, ct, evaluate_red_lines(t, ct), [],
                          taraflar=(["PRATİK İŞLEM"], ["DIŞ HİZMET SAĞLAYICI"]))
    assert "PRATİK İŞLEM" in tb
    assert "DIŞ HİZMET SAĞLAYICI" in tb
    assert "ALICI" in tb


def test_gorev_blogu_sade_anlatimi_tasir():
    """Model, hukukcu olmayan okuyucunun anlayacagi register'da yazsin diye."""
    from app.pipeline.analyze import build_task_block
    from app.playbook.loader import load_playbook

    ct = load_playbook()["LIMITATION_OF_LIABILITY"]
    assert ct.plain_tr, "sade anlatım yüklenmemiş"
    tb = build_task_block("12", "SORUMLULUK", "Sorumluluk sınırlıdır.", ct, [], [])
    assert "SADE ANLATIMI" in tb
    assert ct.plain_tr.strip()[:40] in tb


def test_sema_gereksiz_uretimi_sinirlar():
    """Model ayni sorunu parcalara bolerek raporu sisiremesin."""
    from app.pipeline.analyze import FINDING_SCHEMA

    dizi = FINDING_SCHEMA["properties"]["findings"]
    assert dizi["maxItems"] == 3, "madde başına bulgu sınırı yok"
    alanlar = dizi["items"]["properties"]
    assert alanlar["rationale"]["maxLength"] <= 800
    assert alanlar["title"]["maxLength"] <= 150


def test_kirmizi_cizgi_metinleri_taraf_adina_sabitlenmemis():
    """Bu metinler hem modele checklist olarak gidiyor hem rapora baslik oluyor."""
    from app.playbook.loader import load_playbook

    # "Banka sırrı" hukuki bir kavramdir; istisna.
    ISTISNA = {"Banka sırrı / müşteri sırrı kavramına atıf yok"}
    kotu = [(k, rl.text) for k, c in load_playbook().items() for rl in c.red_lines
            if "banka" in rl.text.lower() and rl.text not in ISTISNA]
    assert not kotu, f"taraf adına sabitlenmiş metinler: {kotu}"


def test_prompt_uydurmayi_ve_sismeyi_acikca_yasaklar():
    from app.pipeline.analyze import SYSTEM_PROMPT

    p = SYSTEM_PROMPT.lower()
    assert "uydurma" in p
    assert "otomatik olarak silinir" in p          # alıntı doğrulaması caydırıcı
    assert "bulgu uretme" in p or "bulgu üretme" in p
    assert "tekrarlama" in p
