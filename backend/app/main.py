"""FastAPI uygulamasi.

Frontend bilincli olarak incedir: kullanici dosyayi birakir, sistem her seyi kendisi
yapar ve sonunda sonuc belgesini verir. Manuel adim yoktur.
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks, Body, Cookie, Depends, FastAPI, File, Form, HTTPException,
    Request, Response, UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import select

from . import runner
from .config import settings
from .db import engine, ensure_schema, read_session, session_scope
from .llm.provider import active_model, get_provider
from .models import AnalysisRun, Base, Contract, Finding, LLMCall, Report
from . import audit, auth
from . import runtime_settings as rt
from .llm import provider as prov
from .pipeline import ocr as ocr_mod
from .playbook.loader import load_playbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

ALLOWED_SUFFIX = {".pdf", ".docx", ".txt"}
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "samples"

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Acilis: sema, playbook, saglayici, oksuz kurtarma, periyodik tarayici."""
    Base.metadata.create_all(engine)
    ensure_schema()
    pb = load_playbook()
    provider = get_provider()
    log.info("Playbook: %d madde tipi | Saglayici: %s", len(pb), provider.name)
    if not provider.is_llm:
        log.warning(
            "Model API anahtari tanimli degil - kural tabanli modda calisiliyor. "
            "Model bulgulari ve sozlesmeye ozgu alternatif metin uretimi devre disi."
        )
    if settings.auth_enabled:
        d = auth.durum()
        if d.uretilen_parola:
            log.warning("=" * 68)
            log.warning("  GIRIS PAROLASI URETILDI: %s", d.uretilen_parola)
            log.warning("  Bu parola yalnizca simdi gosterilir. Kaydedin.")
            log.warning("  Kalici parola icin .env icinde APP_PASSWORD tanimlayin.")
            log.warning("=" * 68)
        else:
            log.info("Kimlik dogrulama etkin (parola tanimli)")
    else:
        log.warning("KIMLIK DOGRULAMA KAPALI (AUTH_ENABLED=0) - yalnizca gelistirme icin!")

    hazir, neden = ocr_mod.kullanilabilir()
    log.info("OCR: %s", "hazır (%s)" % "+".join(ocr_mod.diller()[:4]) if hazir else f"kullanılamıyor — {neden}")

    n = runner.recover_orphans()
    if n:
        log.warning("%d yarim kalmis analiz kaldigi yerden devam ettiriliyor", n)
    runner.start_sweeper()
    try:
        yield
    finally:
        runner.stop_sweeper()


app = FastAPI(title="Sozlesme Feneri", version="1.0.0", lifespan=lifespan)


def _safe_name(name: str) -> str:
    name = Path(name or "belge").name
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name[:120] or "belge"


# --------------------------------------------------------------------------- #
# Kimlik doğrulama
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def login(request: Request, response: Response, password: str = Body(..., embed=True)) -> dict:
    ip = (request.client.host if request.client else "?")
    if not auth.giris_denenebilir(ip):
        audit.kaydet(request, "?", "LOGIN_BLOCKED", detay="çok fazla deneme")
        raise HTTPException(429, "Çok fazla başarısız deneme. Birkaç dakika bekleyin.")

    if not auth._dogrula_parola(password, auth.durum().parola_hash):
        auth.giris_denemesi_kaydet(ip)
        audit.kaydet(request, "?", "LOGIN_FAILED")
        raise HTTPException(401, "Parola hatalı")

    auth.giris_sifirla(ip)
    token = auth.oturum_uret()
    response.set_cookie(
        auth.CEREZ_ADI, token, httponly=True, samesite="lax",
        secure=settings.cookie_secure, max_age=settings.session_hours * 3600, path="/",
    )
    audit.kaydet(request, "kullanici", "LOGIN")
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    response.delete_cookie(auth.CEREZ_ADI, path="/")
    audit.kaydet(request, "kullanici", "LOGOUT")
    return {"ok": True}


@app.get("/api/session")
def session_durumu(feneri_oturum: str | None = Cookie(default=None)) -> dict:
    """Arayüz açılışta bunu sorar.

    Uygulama herkese açıktır; giriş yalnızca sunucunun LLM anahtarını ve
    ayar ekranını açar. Bu uç korumasızdır, yoksa arayüz açılışta kilitlenir.

    `feneri_oturum` çerez olarak okunur — düz `str | None` yazılırsa FastAPI
    onu sorgu parametresi sayar ve çerez hiç ulaşmaz.
    """
    kullanici = auth.oturum_coz(feneri_oturum) if feneri_oturum else None
    return {
        "auth_required": settings.auth_enabled,
        "authenticated": bool(kullanici) or not settings.auth_enabled,
        "kullanici": kullanici or "",
    }


@app.post("/api/password")
def change_password(request: Request, new_password: str = Body(..., embed=True),
                    kullanici: str = Depends(auth.require_user)) -> dict:
    if len(new_password) < 8:
        raise HTTPException(400, "Parola en az 8 karakter olmalı")
    auth.parola_degistir(new_password)
    audit.kaydet(request, kullanici, "PASSWORD_CHANGED")
    return {"ok": True}


@app.get("/api/audit")
def audit_kayitlari(limit: int = 200, kullanici: str = Depends(auth.require_user)) -> dict:
    from .models import AuditLog

    with read_session() as s:
        rows = list(s.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)))
        return {"entries": [
            {"at": r.at.isoformat() if r.at else "", "user": r.user, "action": r.action,
             "entity_type": r.entity_type, "entity_id": r.entity_id, "ip": r.ip,
             "detail": r.detail}
            for r in rows]}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    f = WEB_DIR / "index.html"
    if not f.exists():
        return HTMLResponse("<h1>web/index.html bulunamadi</h1>", status_code=500)
    return HTMLResponse(f.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    p = get_provider()
    return {
        "ok": True,
        "provider": p.name,
        # Secim nereden geliyor: kayitli arayuz ayari mi, ortam degiskeni mi.
        # Kayitli ayar ortami sessizce eziyordu ve sebebi hicbir yerde yazmiyordu.
        "provider_source": rt.saglayici_kaynagi(),
        "model": active_model(p),
        "playbook_size": len(load_playbook()),
        "model_error": rt.son_hata(),
        "ocr": {"ready": ocr_mod.kullanilabilir()[0],
                "detail": ocr_mod.kullanilabilir()[1],
                "languages": ocr_mod.diller()},
        "limits": {
            "max_llm_calls": settings.max_llm_calls,
            "max_cost_usd": settings.max_cost_usd,
            "max_llm_clauses": settings.max_llm_clauses,
            "lenses": settings.enable_lenses,
            "rebuttal": settings.enable_rebuttal,
        },
    }


# --------------------------------------------------------------------------- #
# Ayarlar — kullanıcı kendi API anahtarını ve modelini girer.
# GÜVENLİK: uygulamada kimlik doğrulama yok; bu uçlar da korumasızdır.
# Kapalı ağ / tek kullanıcı kurulumu için tasarlandı (bkz. docs/10 B1).
# --------------------------------------------------------------------------- #
@app.get("/api/settings")
def get_settings(kullanici: str = Depends(auth.require_user)) -> dict:
    r = rt.load()
    saglayici = rt.etkin_saglayici()
    etkin = get_provider()
    return {
        "provider": r.provider or "",
        "effective_provider": etkin.name,
        "model": r.model or "",
        "effective_model": prov.active_model(etkin),
        "key_set": bool(r.api_key),
        "key_masked": r.masked_key(),
        "key_source": rt.anahtar_kaynagi(saglayici if saglayici != "auto" else etkin.name),
        "base_url": r.base_url or "",
        "effective_base_url": rt.etkin_base_url(etkin.name),
        "price_in": r.price_in or 0,
        "price_out": r.price_out or 0,
        "price_source": "ui" if (r.price_in or r.price_out) else "table",
        "known_prices": {m: {"in": p[0], "out": p[1]} for m, p in prov.PRICING.items()},
        "model_error": rt.son_hata(),
        "providers": list(rt.SAGLAYICILAR),
        "model_options": rt.MODEL_SECENEKLERI,
        "presets": rt.HAZIR_UC_NOKTALAR,
        "updated_at": r.updated_at,
    }


@app.put("/api/settings")
def put_settings(
    request: Request,
    provider: str | None = Body(None),
    api_key: str | None = Body(None),
    model: str | None = Body(None),
    base_url: str | None = Body(None),
    price_in: float | None = Body(None),
    price_out: float | None = Body(None),
    kullanici: str = Depends(auth.require_user),
) -> dict:
    if provider is not None and provider not in rt.SAGLAYICILAR and provider != "":
        raise HTTPException(400, f"Geçersiz sağlayıcı: {provider}")
    if api_key is not None:
        api_key = api_key.strip()
    if model is not None:
        model = model.strip()
    if base_url is not None:
        base_url = base_url.strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise HTTPException(400, "Uç nokta adresi http:// veya https:// ile başlamalı")
    if provider == "custom" and not (base_url or rt.etkin_base_url("custom")):
        raise HTTPException(400, "'Diğer' sağlayıcı için uç nokta adresi (base URL) gerekli")

    for ad, deger in (("price_in", price_in), ("price_out", price_out)):
        if deger is not None and deger < 0:
            raise HTTPException(400, f"{ad} negatif olamaz")

    rt.save(provider=provider, api_key=api_key, model=model, base_url=base_url,
            price_in=price_in, price_out=price_out)
    rt.hata_temizle()              # yeni ayar => eski hata gecersiz
    prov.reset_provider()          # yeni ayarla yeniden kurulsun
    etkin = get_provider()
    audit.kaydet(request, kullanici, "SETTINGS_CHANGED", "settings", "",
                 f"sağlayıcı={etkin.name} model={prov.active_model(etkin)} "
                 f"anahtar={'değişti' if api_key else 'değişmedi'}")
    log.info("Ayarlar güncellendi · sağlayıcı=%s model=%s", etkin.name, prov.active_model(etkin))
    return get_settings()


@app.delete("/api/settings/key")
def delete_key(request: Request,
               kullanici: str = Depends(auth.require_user)) -> dict:
    audit.kaydet(request, kullanici, "API_KEY_CLEARED", "settings")
    rt.clear_key()
    rt.hata_temizle()
    prov.reset_provider()
    return get_settings()


@app.post("/api/settings/use-rules")
def use_rules(kullanici: str = Depends(auth.require_user)) -> dict:
    """Kullanıcı 'model kullanmadan devam et' derse: kural tabanlı moda geçer."""
    rt.save(provider="heuristic")
    rt.hata_temizle()
    prov.reset_provider()
    return get_settings()


@app.post("/api/settings/test")
def test_settings(
    provider: str = Body(...),
    api_key: str | None = Body(None),
    model: str | None = Body(None),
    base_url: str | None = Body(None),
    price_in: float | None = Body(None),
    price_out: float | None = Body(None),
    kullanici: str = Depends(auth.require_user),
) -> dict:
    """Girilen anahtarı tek küçük çağrıyla dener. Kaydetmez."""
    anahtar = (api_key or "").strip() or rt.etkin_anahtar(provider)
    uc = (base_url or "").strip().rstrip("/") or rt.etkin_base_url(provider)
    # Anahtar ve uc nokta kayitli ayara duserken model dusmuyordu: kayitli bir
    # yapilandirmayi govdesiz sinamak "model adi girmelisiniz" hatasi veriyordu.
    model = (model or "").strip() or rt.etkin_model(provider)
    yerel = "localhost" in uc or "127.0.0.1" in uc
    if not anahtar and not yerel:
        return {"ok": False, "detail": "API anahtarı girilmedi"}
    if provider in ("openai", "custom") and not uc:
        return {"ok": False, "detail": "Uç nokta adresi (base URL) girilmedi"}
    if provider in ("openai", "custom") and not (model or "").strip():
        return {"ok": False, "detail": "Bu sağlayıcı için model adı girmelisiniz"}
    ok, detay = prov.dogrula(provider, anahtar or "yok", model, uc)
    return {"ok": ok, "detail": detay}


@app.post("/api/settings/models")
def list_models(
    provider: str = Body("gemini"),
    api_key: str | None = Body(None),
    base_url: str | None = Body(None),
    kullanici: str = Depends(auth.require_user),
) -> dict:
    """Sağlayıcıdan gerçek model listesini çeker.

    POST'tur çünkü API anahtarı gövdede taşınır: sorgu dizesinde gitseydi
    ters vekil erişim kayıtlarına ve tarayıcı geçmişine düz metin yazılırdı.

    Gemini ve Anthropic kendi uç noktalarını, OpenAI uyumlu servisler
    `GET /v1/models` ucunu kullanır — bu uç DeepSeek, Groq, OpenRouter,
    Ollama ve vLLM'de de vardır.
    """
    import json as _j
    import urllib.error
    import urllib.request

    anahtar = (api_key or "").strip() or rt.etkin_anahtar(provider)

    if provider == "gemini":
        if not anahtar:
            return {"models": [], "detail": "API anahtarı gerekli"}
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=50"
        basliklar = {"x-goog-api-key": anahtar}
    elif provider == "anthropic":
        if not anahtar:
            return {"models": [], "detail": "API anahtarı gerekli"}
        url = "https://api.anthropic.com/v1/models?limit=100"
        basliklar = {"x-api-key": anahtar, "anthropic-version": "2023-06-01"}
    elif provider in ("openai", "custom"):
        uc = (base_url or "").strip().rstrip("/") or rt.etkin_base_url(provider)
        if not uc:
            return {"models": [], "detail": "Uç nokta adresi gerekli"}
        url = f"{uc}/models"
        basliklar = {"Authorization": f"Bearer {anahtar or 'yok'}"}
    else:
        return {"models": [], "detail": "Bu sağlayıcı model listelemeyi desteklemiyor"}

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=basliklar),
                                    timeout=20) as r:
            d = _j.load(r)
        if provider == "gemini":
            adlar = [m["name"].split("/")[-1] for m in d.get("models", [])]
        elif provider == "anthropic":
            adlar = [m.get("id", "") for m in (d.get("data") or []) if m.get("id")]
        else:
            adlar = [m.get("id", "") for m in (d.get("data") or []) if m.get("id")]
        uygun = [a for a in adlar if a and "tts" not in a and "embedding" not in a
                 and "whisper" not in a]
        return {"models": sorted(set(uygun)), "detail": ""}
    except urllib.error.HTTPError as exc:
        return {"models": [], "detail": f"HTTP {exc.code} — uç nokta veya anahtar hatalı olabilir"}
    except Exception as exc:
        return {"models": [], "detail": str(exc)[:140]}


@app.post("/api/contracts")
async def upload(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    contract_type: str = Form("SAAS"),
    involves_personal_data: bool = Form(True),
    is_outsourcing: bool = Form(False),
    kullanici: str = Depends(auth.optional_user),
) -> JSONResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"Desteklenmeyen dosya türü: {suffix or '(yok)'}. PDF, DOCX veya TXT yükleyin.")

    data = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(400, f"Dosya {settings.max_upload_mb} MB sınırını aşıyor.")
    if not data:
        raise HTTPException(400, "Dosya boş.")

    with session_scope() as s:
        c = Contract(
            title=file.filename or "",
            filename=_safe_name(file.filename or ""),
            mime=file.content_type or "",
            contract_type=contract_type,
            # Sunucunun LLM anahtari yalnizca giris yapmis kullaniciya acilir.
            model_izinli=bool(kullanici),
            involves_personal_data=involves_personal_data,
            is_outsourcing=is_outsourcing,
            size_bytes=len(data),
        )
        s.add(c)
        s.flush()

        dest = settings.storage_dir / "uploads" / c.id
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / (c.filename if Path(c.filename).suffix else c.filename + suffix)
        path.write_bytes(data)
        c.storage_path = str(path)
        cid = c.id

    audit.kaydet(request, kullanici, "UPLOAD", "contract", cid,
                 f"{file.filename} · {len(data)} bayt · {contract_type}")
    runner.start(cid)
    return JSONResponse({"contract_id": cid}, status_code=201)


@app.post("/api/demo")
def demo(request: Request,
         kullanici: str = Depends(auth.optional_user)) -> JSONResponse:
    """Pakete gomulu ornek sozlesmeyi analiz eder.

    Elinde sozlesme olmayan bir kullanicinin sistemi denemesi icin; ayrica
    kurulum sonrasi duman testi olarak da kullanilir.
    """
    src = SAMPLE_DIR / "ornek-saas-sozlesmesi.txt"
    if not src.exists():
        raise HTTPException(404, "Örnek sözleşme bulunamadı")
    data = src.read_bytes()

    with session_scope() as s:
        c = Contract(
            title="Ornek SaaS Tedarik Sozlesmesi",
            filename=src.name,
            mime="text/plain",
            contract_type="SAAS",
            involves_personal_data=True,
            is_outsourcing=True,
            size_bytes=len(data),
            model_izinli=bool(kullanici),
        )
        s.add(c)
        s.flush()
        dest = settings.storage_dir / "uploads" / c.id
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / src.name
        path.write_bytes(data)
        c.storage_path = str(path)
        cid = c.id

    audit.kaydet(request, kullanici, "UPLOAD", "contract", cid,
                 f"{src.name} · {len(data)} bayt · SAAS (örnek)")
    runner.start(cid)
    return JSONResponse({"contract_id": cid}, status_code=201)


@app.get("/api/contracts/{contract_id}/progress")
def progress(contract_id: str, kullanici: str = Depends(auth.optional_user)) -> dict:
    data = runner.progress(contract_id)
    if not data:
        raise HTTPException(404, "Sözleşme bulunamadı")
    return data


@app.post("/api/contracts/{contract_id}/resume")
def resume(contract_id: str, reanalyze: bool = False, kullanici: str = Depends(auth.optional_user)) -> dict:
    """Yarım kalan analizi kaldığı yerden devam ettirir.

    Tamamlanmış bir analiz için varsayılan olarak HİÇBİR ŞEY YAPMAZ: baştan
    çalıştırmak mevcut rapor bağlantılarını geçersiz kılar ve boşuna model
    maliyeti doğurur. Yeniden analiz isteniyorsa `?reanalyze=true` gerekir.
    """
    with session_scope() as s:
        if s.get(Contract, contract_id) is None:
            raise HTTPException(404, "Sözleşme bulunamadı")
        run = s.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.contract_id == contract_id)
            .order_by(AnalysisRun.started_at.desc())
        )
        durum = run.status if run else ""

    if runner.is_running(contract_id):
        return {"started": False, "reason": "Analiz zaten çalışıyor"}
    if durum == "DONE" and not reanalyze:
        return {"started": False,
                "reason": "Analiz zaten tamamlanmış. Yeniden çalıştırmak için "
                          "reanalyze=true gönderin."}

    runner.start(contract_id)
    return {"started": True, "reanalyzed": durum == "DONE"}


@app.post("/api/contracts/{contract_id}/cancel")
def cancel(contract_id: str, request: Request,
           kullanici: str = Depends(auth.optional_user)) -> dict:
    """Analizi iptal eder. İşlem bir sonraki güvenli noktada durur;
    o ana kadar tamamlanmış aşamalar korunur ve devam ettirilebilir."""
    with session_scope() as s:
        if s.get(Contract, contract_id) is None:
            raise HTTPException(404, "Sözleşme bulunamadı")
    ok = runner.cancel(contract_id)
    audit.kaydet(request, kullanici, "ANALYSIS_CANCELLED", "contract", contract_id)
    return {"cancelled": ok,
            "reason": "" if ok else "Analiz zaten tamamlanmış veya durmuş"}


@app.get("/api/contracts/{contract_id}/findings")
def findings(contract_id: str, kullanici: str = Depends(auth.optional_user)) -> dict:
    with read_session() as s:
        rows = list(s.scalars(select(Finding).where(Finding.contract_id == contract_id)))
        order = {"KRITIK": 0, "YUKSEK": 1, "ORTA": 2, "DUSUK": 3, "BILGI": 4}
        rows.sort(key=lambda f: (order.get(f.severity, 9), -f.confidence))
        return {
            "count": len(rows),
            "findings": [
                {
                    "id": f.id, "clause_number": f.clause_number, "code": f.code,
                    "finding_type": f.finding_type, "severity": f.severity,
                    "title": f.title, "rationale": f.rationale, "quote": f.quote,
                    "legal_basis": list(f.legal_basis or []),
                    "proposed_text": f.proposed_text, "negotiation_note": f.negotiation_note,
                    "confidence": f.confidence, "detected_by": f.detected_by,
                    "lens": f.lens, "rebuttal": f.rebuttal,
                }
                for f in rows
            ],
        }


@app.get("/api/contracts/{contract_id}/usage")
def usage(contract_id: str, kullanici: str = Depends(auth.optional_user)) -> dict:
    """Bu sözleşme için harcanan token ve maliyet dökümü."""
    with read_session() as s:
        c = s.get(Contract, contract_id)
        if c is None:
            raise HTTPException(404, "Sözleşme bulunamadı")
        calls = list(s.scalars(select(LLMCall).where(LLMCall.contract_id == contract_id)))
        ozet = runner.usage_summary(calls)
        # O anki yapilandirmayi degil, BU analizin gercekte kullandigini bildir:
        # parolasiz yuklenen sozlesmeler kural katmaniyla islenir.
        if c.model_izinli:
            ozet["provider"] = get_provider().name
            ozet["model"] = active_model(get_provider())
        else:
            ozet["provider"] = "heuristic"
            ozet["model"] = None
        return ozet


@app.get("/api/dashboard")
def dashboard(kullanici: str = Depends(auth.optional_user)) -> dict:
    """Portföy görünümü: tüm sözleşmelerin toplu durumu.

    Tek bir sözleşmeyi incelemek ayrı, portföyü yönetmek ayrı bir iştir.
    Bu uç ikincisini besler: hangi banka, hangi tedarikçi, hangi risk bandı,
    en sık ihlal edilen maddeler.
    """
    from collections import Counter

    from .models import Clause
    from .playbook.loader import load_playbook

    pb = load_playbook()
    with read_session() as s:
        sozlesmeler = list(s.scalars(select(Contract).order_by(Contract.created_at.desc())))
        bulgular = list(s.scalars(select(Finding)))

        bulgu_ix: dict[str, list] = {}
        for f in bulgular:
            bulgu_ix.setdefault(f.contract_id, []).append(f)

        satirlar = []
        for c in sozlesmeler:
            fs = bulgu_ix.get(c.id, [])
            sayac = Counter(f.severity for f in fs)
            satirlar.append({
                "id": c.id,
                "alici": (c.meta_json or {}).get("alici") or "—",
                "counterparty": c.counterparty or "—",
                "filename": c.filename,
                "contract_type": c.contract_type,
                "status": c.status,
                "risk_score": c.risk_score,
                "risk_band": c.risk_band,
                "value_text": c.value_text or "—",
                "term_text": c.term_text or "—",
                "kritik": sayac.get("KRITIK", 0),
                "yuksek": sayac.get("YUKSEK", 0),
                "orta": sayac.get("ORTA", 0),
                "toplam": len(fs),
                "eksik": sum(1 for f in fs if f.finding_type == "MISSING"),
                "created_at": c.created_at.isoformat() if c.created_at else "",
            })

        bitmis = [r for r in satirlar if r["risk_score"] is not None]
        bant = Counter(r["risk_band"] for r in bitmis)

        # En sik ihlal edilen madde tipleri
        ihlal = Counter(f.code for f in bulgular if f.severity in ("KRITIK", "YUKSEK"))
        en_sik = [{"code": k, "name": pb[k].name_tr if k in pb else k, "adet": v}
                  for k, v in ihlal.most_common(8)]

        # En riskli tedarikciler
        ted: dict[str, list] = {}
        for r in bitmis:
            ted.setdefault(r["counterparty"], []).append(r["risk_score"])
        en_riskli = sorted(
            ({"ad": k, "sozlesme": len(v), "ort_skor": round(sum(v) / len(v), 1)}
             for k, v in ted.items() if k != "—"),
            key=lambda x: x["ort_skor"])[:6]

        return {
            "ozet": {
                "toplam": len(satirlar),
                "tamamlanan": len(bitmis),
                "kirmizi": bant.get("KIRMIZI", 0),
                "sari": bant.get("SARI", 0),
                "yesil": bant.get("YESIL", 0),
                "ort_skor": round(sum(r["risk_score"] for r in bitmis) / len(bitmis), 1) if bitmis else None,
                "toplam_bulgu": len(bulgular),
                "kritik_bulgu": sum(1 for f in bulgular if f.severity == "KRITIK"),
            },
            "sozlesmeler": satirlar,
            "en_sik_ihlal": en_sik,
            "en_riskli_tedarikciler": en_riskli,
        }


@app.get("/api/reports/{report_id}")
def download(report_id: str, request: Request,
             kullanici: str = Depends(auth.optional_user)) -> FileResponse:
    with read_session() as s:
        r = s.get(Report, report_id)
        if r is None or not Path(r.path).exists():
            raise HTTPException(404, "Rapor bulunamadı")
        audit.kaydet(request, kullanici, "REPORT_DOWNLOAD", "report", report_id,
                     f"{r.fmt} · {r.filename}")
        if r.fmt == "HTML":
            # Indirilmek yerine tarayicida acilir.
            return HTMLResponse(Path(r.path).read_text(encoding="utf-8"))
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if r.fmt in ("DOCX", "REDLINE")
            else "application/json"
        )
        return FileResponse(r.path, filename=r.filename, media_type=media)


@app.get("/api/contracts")
def list_contracts(limit: int = 30, kullanici: str = Depends(auth.optional_user)) -> dict:
    with read_session() as s:
        rows = list(
            s.scalars(select(Contract).order_by(Contract.created_at.desc()).limit(limit))
        )
        return {
            "contracts": [
                {
                    "id": c.id, "filename": c.filename, "status": c.status,
                    "risk_score": c.risk_score, "risk_band": c.risk_band,
                    "counterparty": c.counterparty,
                    "created_at": c.created_at.isoformat() if c.created_at else "",
                }
                for c in rows
            ]
        }
