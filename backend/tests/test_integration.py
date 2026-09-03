"""Entegrasyon testleri — HTTP seviyesinde, gercek uygulama uzerinden.

Birim testleri parcalarin dogrulugunu, bunlar SISTEMIN dogrulugunu olcer:
yukleme -> arka plan analizi -> ilerleme -> dort belge -> indirme.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import engine, ensure_schema
from app.main import app
from app.models import Base

ORNEK_DIR = Path(__file__).resolve().parent.parent.parent / "samples"
PDF = ORNEK_DIR / "ornek-saas-sozlesmesi.pdf"
TXT = ORNEK_DIR / "ornek-saas-sozlesmesi.txt"


@pytest.fixture(scope="module")
def istemci():
    Base.metadata.create_all(engine)
    ensure_schema()
    with TestClient(app) as c:
        yield c


def _bekle(istemci, cid: str, saniye: int = 60) -> dict:
    son = {}
    bitis = time.time() + saniye
    while time.time() < bitis:
        son = istemci.get(f"/api/contracts/{cid}/progress").json()
        if son.get("run_status") in ("DONE", "FAILED"):
            return son
        time.sleep(0.2)
    raise AssertionError(f"analiz {saniye} sn içinde bitmedi: {son.get('run_status')}")


def _yukle(istemci, yol: Path, **alanlar) -> str:
    veri = {"contract_type": "SAAS", "involves_personal_data": "true",
            "is_outsourcing": "true", **alanlar}
    with open(yol, "rb") as fh:
        r = istemci.post("/api/contracts", files={"file": (yol.name, fh)}, data=veri)
    assert r.status_code == 201, r.text
    return r.json()["contract_id"]


# --------------------------------------------------------------- temel
def test_saglik_ucu(istemci):
    d = istemci.get("/api/health").json()
    assert d["ok"] is True
    assert d["playbook_size"] >= 40
    assert "limits" in d and d["limits"]["max_llm_calls"] > 0


def test_ana_sayfa_yuklenir(istemci):
    r = istemci.get("/")
    assert r.status_code == 200
    assert "Sözleşmedeki riski" in r.text


# --------------------------------------------------------------- ana akış
@pytest.fixture(scope="module")
def tamamlanmis(istemci):
    """Tek bir analiz kosulur, birden cok test onu inceler."""
    cid = _yukle(istemci, PDF)
    p = _bekle(istemci, cid)
    assert p["run_status"] == "DONE", p.get("error")
    return cid, p


def test_uctan_uca_analiz_tamamlanir(tamamlanmis):
    _, p = tamamlanmis
    assert p["percent"] == 100.0
    assert all(a["status"] == "DONE" for a in p["stages"]), \
        [a["key"] for a in p["stages"] if a["status"] != "DONE"]
    assert p["risk_score"] is not None
    assert p["risk_band"] in ("YESIL", "SARI", "KIRMIZI")
    assert p["counterparty"], "karşı taraf çıkarılamadı"


def test_on_asama_da_kaydedilir(tamamlanmis):
    _, p = tamamlanmis
    assert len(p["stages"]) == 10
    anahtarlar = [a["key"] for a in p["stages"]]
    assert anahtarlar[0] == "INGEST" and anahtarlar[-1] == "REPORT"
    risk = next(a for a in p["stages"] if a["key"] == "RISK")
    assert risk["items_total"] > 0, "madde bazlı ilerleme kaydedilmemiş"


def test_dort_belge_uretilir(tamamlanmis):
    _, p = tamamlanmis
    formatlar = {r["fmt"] for r in p["reports"]}
    assert formatlar == {"DOCX", "REDLINE", "HTML", "JSON"}, formatlar
    assert all(r["size_bytes"] > 1000 for r in p["reports"])


def test_belgeler_indirilebilir(istemci, tamamlanmis):
    _, p = tamamlanmis
    for r in p["reports"]:
        cevap = istemci.get(f"/api/reports/{r['id']}")
        assert cevap.status_code == 200, r["fmt"]
        assert len(cevap.content) > 1000
        if r["fmt"] in ("DOCX", "REDLINE"):
            assert cevap.content[:2] == b"PK", f"{r['fmt']} geçerli bir Office dosyası değil"
        if r["fmt"] == "HTML":
            # Tarayicida acilmali, indirilmemeli
            assert "text/html" in cevap.headers["content-type"]
            assert "Sözleşme Risk Raporu" in cevap.text
            assert "Model kullanımı" in cevap.text or "Bulgular" in cevap.text


def test_redline_gercek_degisiklik_izleme_icerir(istemci, tamamlanmis):
    import io
    import zipfile

    _, p = tamamlanmis
    rid = next(r["id"] for r in p["reports"] if r["fmt"] == "REDLINE")
    icerik = istemci.get(f"/api/reports/{rid}").content
    xml = zipfile.ZipFile(io.BytesIO(icerik)).read("word/document.xml").decode()
    assert "<w:ins " in xml and "<w:del " in xml


def test_bulgular_ucu(istemci, tamamlanmis):
    cid, _ = tamamlanmis
    d = istemci.get(f"/api/contracts/{cid}/findings").json()
    assert d["count"] > 0
    ilk = d["findings"][0]
    for alan in ("clause_number", "code", "finding_type", "severity", "title",
                 "rationale", "quote", "legal_basis", "proposed_text", "confidence"):
        assert alan in ilk, f"{alan} eksik"
    # En siddetli bulgu basta
    siralama = {"KRITIK": 0, "YUKSEK": 1, "ORTA": 2, "DUSUK": 3, "BILGI": 4}
    puanlar = [siralama.get(f["severity"], 9) for f in d["findings"]]
    assert puanlar == sorted(puanlar), "bulgular şiddete göre sıralanmamış"


def test_kullanim_ucu(istemci, tamamlanmis):
    cid, _ = tamamlanmis
    d = istemci.get(f"/api/contracts/{cid}/usage").json()
    for alan in ("calls", "input_tokens", "output_tokens", "total_tokens",
                 "cost_usd", "by_agent", "provider"):
        assert alan in d, f"{alan} eksik"
    assert d["total_tokens"] == (
        d["input_tokens"] + d["output_tokens"] + d["cache_read_tokens"]
    )
    assert d["cost_usd"] >= 0


def test_sozlesme_listesi(istemci, tamamlanmis):
    cid, _ = tamamlanmis
    d = istemci.get("/api/contracts").json()
    assert any(c["id"] == cid for c in d["contracts"])


# --------------------------------------------------------------- hata yolları
def test_desteklenmeyen_dosya_turu_reddedilir(istemci):
    r = istemci.post("/api/contracts", files={"file": ("kotu.exe", b"MZ" + b"x" * 500)})
    assert r.status_code == 400
    assert "dosya türü" in r.json()["detail"].lower()


def test_bos_dosya_reddedilir(istemci):
    r = istemci.post("/api/contracts", files={"file": ("bos.txt", b"")})
    assert r.status_code == 400


def test_olmayan_sozlesme_404(istemci):
    assert istemci.get("/api/contracts/yokboyle/progress").status_code == 404
    assert istemci.get("/api/contracts/yokboyle/usage").status_code == 404
    assert istemci.post("/api/contracts/yokboyle/resume").status_code == 404


def test_olmayan_rapor_404(istemci):
    assert istemci.get("/api/reports/yokboyle").status_code == 404


def test_taranmis_pdf_ocr_yoksa_net_hata_verir(istemci, tmp_path):
    """OCR kurulu degilse sessizce bos analiz uretmemeli."""
    from app.pipeline import ocr as ocr_mod

    hazir, _ = ocr_mod.kullanilabilir()
    pymupdf = pytest.importorskip("pymupdf")

    kaynak = pymupdf.open(str(PDF))
    hedef = pymupdf.open()
    for i in range(kaynak.page_count):
        pix = kaynak.load_page(i).get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4), alpha=False)
        sayfa = hedef.new_page(width=pix.width * 0.72, height=pix.height * 0.72)
        sayfa.insert_image(sayfa.rect, pixmap=pix)
    yol = tmp_path / "taranmis.pdf"
    hedef.save(str(yol))
    hedef.close()
    kaynak.close()

    cid = _yukle(istemci, yol)
    p = _bekle(istemci, cid, saniye=180)

    if hazir:
        # OCR varsa analiz tamamlanmali
        assert p["run_status"] == "DONE", p.get("error")
    else:
        assert p["run_status"] == "FAILED"
        assert "tesseract" in (p["error"] or "").lower()
        cikarma = next(a for a in p["stages"] if a["key"] == "EXTRACT")
        assert cikarma["attempts"] == 1, "ölümcül hata boşuna tekrarlanmış"


def test_biten_analiz_resume_ile_bastan_calismaz(istemci, tamamlanmis):
    """Gercek hata: /resume bitmis analizi sessizce bastan calistiriyordu.

    Sonuc: mevcut rapor baglantilari gecersiz oluyor ve bosuna model maliyeti
    doguyordu. Yeniden analiz artik acik bir istek gerektiriyor.
    """
    cid, p = tamamlanmis
    onceki = {r["id"] for r in p["reports"]}

    r = istemci.post(f"/api/contracts/{cid}/resume")
    assert r.status_code == 200
    d = r.json()
    assert d["started"] is False, "bitmiş analiz yeniden başlatıldı"
    assert "tamamlanmış" in d["reason"]

    # Rapor kimlikleri degismemis olmali
    sonraki = {x["id"] for x in
               istemci.get(f"/api/contracts/{cid}/progress").json()["reports"]}
    assert sonraki == onceki, "rapor bağlantıları geçersiz kılındı"


def test_txt_yolu_da_calisir(istemci):
    cid = _yukle(istemci, TXT, contract_type="YAZILIM")
    p = _bekle(istemci, cid)
    assert p["run_status"] == "DONE"
    assert any(r["fmt"] == "HTML" for r in p["reports"])


def test_iptal_ucu(istemci, tamamlanmis):
    """Biten analiz icin iptal reddedilmeli, ama uc 200 donmeli."""
    cid, _ = tamamlanmis
    r = istemci.post(f"/api/contracts/{cid}/cancel")
    assert r.status_code == 200
    d = r.json()
    assert d["cancelled"] is False
    assert d["reason"]


def test_olmayan_sozlesme_iptali_404(istemci):
    assert istemci.post("/api/contracts/yokboyle/cancel").status_code == 404


def test_ilerleme_ucu_iptal_alanlarini_dondurur(istemci, tamamlanmis):
    """Arayuz iptal dugmesini bu alanlara gore gosterir."""
    cid, _ = tamamlanmis
    p = istemci.get(f"/api/contracts/{cid}/progress").json()
    assert "cancellable" in p and "cancel_requested" in p
    assert p["cancellable"] is False   # analiz bitmis
    assert p["cancel_requested"] is False


def test_arayuz_yenilemeye_dayanikli(istemci):
    """Sayfa yenilendiginde analize geri baglanmayi saglayan kod mevcut mu?"""
    h = istemci.get("/").text
    assert "localStorage" in h, "analiz kimliği saklanmıyor"
    assert "yenidenBaglan" in h, "yeniden bağlanma yok"
    assert "history.replaceState" in h, "URL'e kimlik yazılmıyor"
    assert "cancelBtn" in h, "iptal düğmesi yok"


def test_kapsam_bilgisi_raporda(istemci, tamamlanmis):
    """Incelenmeyen maddeler raporda gorunmeli; sessizce atlanmamali."""
    import json as _j

    _, p = tamamlanmis
    rid = next(r["id"] for r in p["reports"] if r["fmt"] == "JSON")
    d = _j.loads(istemci.get(f"/api/reports/{rid}").content)
    assert "coverage" in d
    c = d["coverage"]
    assert c["clauses_total"] >= c["clauses_classified"]
    assert isinstance(c["unreviewed"], list)


# --------------------------------------------------------------- ayarlar
def test_ayar_ucu_varsayilan_durumu_dondurur(istemci):
    d = istemci.get("/api/settings").json()
    for alan in ("provider", "effective_provider", "model", "effective_model",
                 "key_set", "key_masked", "key_source", "providers", "model_options"):
        assert alan in d, f"{alan} eksik"
    # Kullanici tek bir saglayiciya kilitlenmemeli
    for beklenen in ("anthropic", "openai", "gemini", "custom", "heuristic"):
        assert beklenen in d["providers"], f"{beklenen} sağlayıcı listesinde yok"

    # Model adlari tek tek sayilmaz; SEVIYE sunulur + "diger" arayuzde eklenir
    for saglayici in ("anthropic", "openai", "gemini"):
        secenekler = d["model_options"][saglayici]
        assert 2 <= len(secenekler) <= 5, f"{saglayici}: fazla/az seçenek"
        for m in secenekler:
            assert m["id"] and m["label"]
    # "custom" icin hazir seviye yok: modeli kullanici girer
    assert d["model_options"]["custom"] == []

    # Bilinen uc noktalar baslangic noktasi olarak sunulmali
    assert len(d["presets"]) >= 5
    adlar = " ".join(u["ad"] for u in d["presets"]).lower()
    assert "deepseek" in adlar and "qwen" in adlar
    assert any("localhost" in u["base_url"] for u in d["presets"]), "yerel seçenek yok"


def test_anahtar_kaydedilir_maskelenir_ve_silinir(istemci):
    r = istemci.put("/api/settings", json={
        "provider": "gemini", "api_key": "AIzaGIZLI1234567890", "model": "gemini-flash-latest"})
    assert r.status_code == 200
    d = r.json()
    assert d["key_set"] is True
    assert d["key_source"] == "ui"
    assert d["effective_provider"] == "gemini"
    assert d["effective_model"] == "gemini-flash-latest"

    # Anahtar HICBIR ZAMAN acik dondurulmemeli
    assert "AIzaGIZLI1234567890" not in r.text
    assert d["key_masked"].startswith("AIza") and "•" in d["key_masked"]

    d2 = istemci.delete("/api/settings/key").json()
    assert d2["key_set"] is False
    assert d2["effective_provider"] == "heuristic"


def test_gecersiz_saglayici_reddedilir(istemci):
    r = istemci.put("/api/settings", json={"provider": "chatgpt"})
    assert r.status_code == 400


def test_ozel_model_adi_kabul_edilir(istemci):
    """Arayuzdeki 'Diğer' secenegi serbest metin gonderir."""
    d = istemci.put("/api/settings", json={
        "provider": "gemini", "api_key": "AIzaTEST0000000000", "model": "gemini-9.9-deneysel"}).json()
    assert d["effective_model"] == "gemini-9.9-deneysel"
    istemci.delete("/api/settings/key")


def test_anahtarsiz_baglanti_testi_net_hata_verir(istemci):
    istemci.delete("/api/settings/key")
    d = istemci.post("/api/settings/test", json={"provider": "gemini"}).json()
    assert d["ok"] is False
    assert "anahtar" in d["detail"].lower()


def test_ayar_sinamasi_kayitli_modeli_kullanir(istemci):
    """Anahtar ve uc nokta kayitli ayara duserken model dusmuyordu: kaydedilmis
    bir yapilandirmayi govdesiz sinamak "model adi girmelisiniz" hatasi
    veriyordu. Arayuzdeki sinama dugmesi model alanini gondermezse ayni hata.
    """
    istemci.put("/api/settings", json={
        "provider": "custom",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3.8-flash",
        "api_key": "deneme-anahtari"})

    d = istemci.post("/api/settings/test", json={"provider": "custom"}).json()
    # Baglanti kurulamayabilir (yerel servis yok) ama model eksikliginden
    # sikayet etmemeli: kayitli deger okunmali.
    assert "model adı girmelisiniz" not in (d.get("detail") or "").lower(), \
        "sınama ucu kayıtlı modeli okumuyor"


def test_ayar_degisikligi_saglayiciyi_yeniden_kurar(istemci):
    """Kaydetmek, calisan surecte saglayiciyi degistirmeli (yeniden baslatma gerekmeden)."""
    istemci.delete("/api/settings/key")
    assert istemci.get("/api/health").json()["provider"] == "heuristic"

    istemci.put("/api/settings", json={"provider": "gemini", "api_key": "AIzaXXXXXXXXXXXX"})
    assert istemci.get("/api/health").json()["provider"] == "gemini"

    istemci.delete("/api/settings/key")
    assert istemci.get("/api/health").json()["provider"] == "heuristic"


def test_ayar_paneli_arayuzde_var(istemci):
    h = istemci.get("/").text
    assert 'id="settings"' in h
    assert "Bağlantıyı test et" in h
    assert "__diger__" in h, "'Diğer' model seçeneği yok"
    assert "kimlik doğrulama yoktur" in h, "güvenlik uyarısı gösterilmiyor"


def test_diger_saglayici_uc_nokta_zorunlu(istemci):
    r = istemci.put("/api/settings", json={"provider": "custom", "model": "qwen-plus"})
    assert r.status_code == 400
    assert "uç nokta" in r.json()["detail"].lower()


def test_gecersiz_uc_nokta_reddedilir(istemci):
    r = istemci.put("/api/settings", json={
        "provider": "custom", "base_url": "deepseek.com", "model": "deepseek-chat"})
    assert r.status_code == 400


def test_openai_uyumlu_saglayici_kaydedilir(istemci):
    """Qwen / DeepSeek / yerel model gibi uclar tek bir 'custom' saglayiciyla kurulur."""
    d = istemci.put("/api/settings", json={
        "provider": "custom",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-DENEME1234567890",
        "model": "deepseek-chat",
    }).json()
    assert d["effective_provider"] == "custom"
    assert d["effective_model"] == "deepseek-chat"
    assert d["effective_base_url"] == "https://api.deepseek.com/v1"
    assert "sk-DENEME1234567890" not in str(d)
    istemci.delete("/api/settings/key")


def test_yerel_model_anahtarsiz_kabul_edilir(istemci):
    """Ollama/vLLM gibi yerel ucler anahtar istemez."""
    d = istemci.put("/api/settings", json={
        "provider": "custom", "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:14b"}).json()
    assert d["effective_provider"] == "custom"
    r = istemci.post("/api/settings/test", json={
        "provider": "custom", "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:14b"}).json()
    # Sunucu yoksa baglanti hatasi verir; "anahtar yok" demez
    assert "anahtar" not in r["detail"].lower()
    istemci.put("/api/settings", json={"provider": "", "base_url": "", "model": ""})


def test_openai_strict_sema_donusumu():
    """OpenAI strict modu her nesnede additionalProperties:false ve tam required ister."""
    from app.llm.provider import _strict_schema

    g = _strict_schema({
        "type": "object",
        "properties": {"a": {"type": "string"},
                       "b": {"type": "array", "items": {"type": "object",
                                                        "properties": {"c": {"type": "number"}}}}},
        "required": ["a"],
    })
    assert g["additionalProperties"] is False
    assert set(g["required"]) == {"a", "b"}
    ic = g["properties"]["b"]["items"]
    assert ic["additionalProperties"] is False and ic["required"] == ["c"]


def test_bilinmeyen_model_maliyeti_uydurulmaz():
    """Kullanicinin kendi ucundaki model icin fiyat bilinmez; 0 doner, tahmin edilmez."""
    from app.llm.provider import Usage, estimate_cost, fiyat_bilinir

    assert fiyat_bilinir("gpt-4o-mini") is True
    assert fiyat_bilinir("qwen-plus") is False
    u = Usage(model="qwen-plus", input_tokens=10000, output_tokens=5000)
    assert estimate_cost(u) == 0.0


# --------------------------------------------------------------- fiyat & geri düşüş
def test_bilinen_model_fiyati_arayuze_sunulur(istemci):
    """Kutular hazir gelsin diye bilinen fiyatlar API'den doner."""
    d = istemci.get("/api/settings").json()
    assert "known_prices" in d
    assert d["known_prices"]["gpt-4o-mini"]["in"] > 0
    assert d["known_prices"]["claude-opus-5"]["out"] > 0
    assert d["price_source"] == "table"


def test_kullanici_fiyati_tabloyu_ezer(istemci):
    """Saglayici fiyati degistirir ve biz guncellemezsek kullanici elle girebilmeli."""
    from app.llm.provider import Usage, estimate_cost, fiyat_bul

    # tablo degeri
    assert fiyat_bul("gpt-4o-mini") == (0.15, 0.6)

    istemci.put("/api/settings", json={"price_in": 9.0, "price_out": 30.0})
    assert fiyat_bul("gpt-4o-mini") == (9.0, 30.0)
    u = Usage(model="gpt-4o-mini", input_tokens=1_000_000, output_tokens=0)
    assert estimate_cost(u) == 9.0

    # bilinmeyen model de artik hesaplanir
    assert fiyat_bul("qwen-plus") == (9.0, 30.0)

    d = istemci.put("/api/settings", json={"price_in": 0, "price_out": 0}).json()
    assert d["price_source"] == "table"
    assert fiyat_bul("qwen-plus") is None


def test_negatif_fiyat_reddedilir(istemci):
    r = istemci.put("/api/settings", json={"price_in": -1})
    assert r.status_code == 400


def test_maliyet_bilinmiyorsa_rapor_uydurmaz(tmp_path):
    from app.pipeline.report_html import build_html

    payload = {
        "contract": {"filename": "x.pdf", "risk_score": 40, "risk_band": "SARI",
                     "meta": {}, "clause_count": 5},
        "findings": [], "counts": {}, "generated_at": "01.01.2026", "engine": "test",
        "method": {},
        "usage": {"calls": 2, "succeeded": 2, "failed": 0, "input_tokens": 1000,
                  "output_tokens": 200, "cache_read_tokens": 0, "total_tokens": 1200,
                  "cost_usd": 0.0, "avg_latency_ms": 100, "cost_known": False,
                  "by_agent": []},
    }
    html = build_html(payload, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "birim fiyatı bilinmediği için" in html
    assert "$0.0000" not in html, "bilinmeyen maliyet 0 dolar gibi gösterilmiş"


# --------------------------------------------------------------- anahtar geri düşüşü
def test_arayuzde_anahtar_yoksa_ortam_degiskeni_kullanilir(istemci, monkeypatch):
    """Kullanici anahtar girmek ZORUNDA degil: .env'deki anahtar devreye girer."""
    from app.config import settings as env_ayar
    from app.llm import provider as prov

    istemci.delete("/api/settings/key")
    monkeypatch.setattr(env_ayar, "google_api_key", "AIzaORTAMDAN123456")
    monkeypatch.setattr(env_ayar, "llm_provider", "auto")   # testlerde heuristic'e sabitli
    prov.reset_provider()

    d = istemci.get("/api/settings").json()
    assert d["key_set"] is False, "arayüzde anahtar yok"
    assert d["effective_provider"] == "gemini", "ortam anahtarı devreye girmedi"
    assert d["key_source"] == "env"


def test_arayuz_anahtari_ortami_ezer(istemci, monkeypatch):
    from app.config import settings as env_ayar
    from app.llm import provider as prov

    monkeypatch.setattr(env_ayar, "google_api_key", "AIzaORTAMDAN123456")
    monkeypatch.setattr(env_ayar, "llm_provider", "auto")
    prov.reset_provider()
    d = istemci.put("/api/settings", json={
        "provider": "gemini", "api_key": "AIzaKULLANICI9999"}).json()
    assert d["key_source"] == "ui"
    istemci.delete("/api/settings/key")


# --------------------------------------------------------------- model hatası akışı
def test_gecersiz_anahtar_hatasi_kullaniciya_bildirilir(istemci):
    """Anahtar bitince kullanici sessizce kural moduna dusmemeli; haberi olmali."""
    from app import runtime_settings as rt

    rt.hata_kaydet("auth", "HTTP 401: invalid api key", "gemini-flash-latest", "gemini")
    d = istemci.get("/api/settings").json()
    assert d["model_error"] is not None
    assert d["model_error"]["kind"] == "auth"
    h = istemci.get("/api/health").json()
    assert h["model_error"]["kind"] == "auth"
    rt.hata_temizle()


def test_kural_motoruyla_devam_secenegi(istemci):
    """Kullanici 'model istemiyorum' derse tek tikla kural moduna gecebilmeli."""
    from app import runtime_settings as rt

    rt.hata_kaydet("quota", "HTTP 429: quota exceeded", "gemini-flash-latest", "gemini")
    d = istemci.post("/api/settings/use-rules").json()
    assert d["effective_provider"] == "heuristic"
    assert d["model_error"] is None, "geçişten sonra hata bandı temizlenmeli"
    istemci.put("/api/settings", json={"provider": ""})


def test_ayar_kaydi_eski_hatayi_temizler(istemci):
    from app import runtime_settings as rt

    rt.hata_kaydet("auth", "HTTP 401", "m", "gemini")
    d = istemci.put("/api/settings", json={"provider": ""}).json()
    assert d["model_error"] is None


def test_arayuzde_fiyat_ve_hata_alanlari_var(istemci):
    h = istemci.get("/").text
    assert 'id="sPin"' in h and 'id="sPout"' in h, "birim fiyat alanları yok"
    assert "maliyet hesabı da\n        gerçekleşir" in h or "maliyet hesabı da" in h
    assert "Kural motoruyla devam et" in h, "kural motoru seçeneği yok"
    assert "Anahtar girmek zorunda değilsiniz" in h


def test_model_kalitesi_aciklamasi_arayuzde(istemci):
    """Kullanici model seciminin sonuca etkisini panelde gormeli."""
    h = istemci.get("/").text
    assert "Daha güçlü model, daha iyi analiz" in h
    assert "en yetenekli modeli seçin" in h
    # Kural katmaninin modelden bagimsiz oldugu da soylenmeli: model secimi
    # her seyi degistirmez, yanlis beklenti olusmasin.
    assert "kural katmanı modelden bağımsız" in h
    assert 'id="sLevel"' in h, "seçilen kademeye göre canlı not alanı yok"


def test_arayuz_javascripti_sozdizimsel_gecerli(istemci, tmp_path):
    """Gercek hata: kapanmamis bir fonksiyon blogu sayfayi tamamen bos birakti.

    Sunucu 200 donuyordu, HTML doluydu, ama JS calismadigi icin ne giris ekrani
    ne uygulama goruluyordu. Bu testin yakaladigi sinif tam olarak budur.
    """
    import shutil
    import subprocess

    h = istemci.get("/").text
    js = h[h.rindex("<script>") + len("<script>"): h.rindex("</script>")]
    assert len(js) > 5000

    node = shutil.which("node")
    if not node:
        pytest.skip("node bulunamadı; sözdizimi denetimi atlandı")

    yol = tmp_path / "arayuz.js"
    yol.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(yol)], capture_output=True, text=True)
    assert r.returncode == 0, f"arayüz JavaScript'i geçersiz:\n{r.stderr[:600]}"


def test_raporda_terimler_aciklaniyor(istemci, tamamlanmis):
    """Son kullanici 'escrow', 'temlik' gibi terimleri anlamak zorunda kalmamali."""
    _, p = tamamlanmis
    rid = next(r["id"] for r in p["reports"] if r["fmt"] == "HTML")
    h = istemci.get(f"/api/reports/{rid}").text

    assert "Bu ne demek?" in h, "bulgularda sade anlatım yok"
    assert "Terimler sözlüğü" in h, "sözlük bölümü yok"
    # Sozlukte gercekten aciklama olmali
    assert "tarafsız bir kuruluşa emanet" in h or "üst sınırıdır" in h


def test_json_ciktisinda_sade_anlatim_tasiniyor(istemci, tamamlanmis):
    import json as _j

    _, p = tamamlanmis
    rid = next(r["id"] for r in p["reports"] if r["fmt"] == "JSON")
    d = _j.loads(istemci.get(f"/api/reports/{rid}").content)
    if d["findings"]:
        f = d["findings"][0]
        assert "plain" in f and f["plain"], "JSON çıktısında sade anlatım yok"
        assert "clause_name" in f
