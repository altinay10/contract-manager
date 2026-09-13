"""Kayıt altyapısı — her olgu kendi tablosunda, okuma tek yerde.

Yerleşim ilkesi:
  * kim, nereden yükledi  -> contracts   (belgenin olgusu)
  * hangi motorla koştu   -> analysis_runs (koşunun olgusu; aynı sözleşme
                             yarın başka modelle yeniden koşabilir)
  * ne yapıldı            -> audit_log   (olayın olgusu, yapısal detayla)
  * ne harcandı           -> llm_calls   (kullanımın olgusu)
  * hepsini bir arada     -> GET /api/contracts/{id}/kunye

Bu dosya hem yerleşimi hem de geçmişi geri doldurmayı doğrular.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from app.db import engine, ensure_schema, geri_doldur, session_scope
from app.main import app
from app.models import AnalysisRun, AuditLog, Base, Contract, LLMCall


@pytest.fixture(scope="module")
def istemci():
    Base.metadata.create_all(engine)
    ensure_schema()
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------- köken: contracts
def test_yukleme_kokeni_sozlesme_satirina_yazilir(istemci):
    """Denetim izini elle eşleştirmeden 'bunu kim, nereden yükledi' cevaplanmalı."""
    r = istemci.post("/api/contracts",
                     files={"file": ("koken.txt", b"deneme metni " * 40)},
                     headers={"User-Agent": "DenemeTarayici/1.0",
                              "X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    assert r.status_code < 400, r.text
    cid = r.json()["contract_id"]
    with session_scope() as s:
        c = s.get(Contract, cid)
        assert c.yukleyen_ip == "203.0.113.9", (
            f"vekil zincirinin İLK girdisi alınmalıydı, alınan: {c.yukleyen_ip!r}"
        )
        assert c.yukleyen_ua == "DenemeTarayici/1.0"


def test_denetim_izi_yapisal_detay_tutar(istemci):
    """Serbest metin sorgulanamıyor; yapısal alan onun için."""
    r = istemci.post("/api/contracts",
                     files={"file": ("yapisal.txt", b"deneme metni " * 40)},
                     data={"contract_type": "HIZMET", "listede_gizli": "true"})
    cid = r.json()["contract_id"]
    with session_scope() as s:
        kayit = s.scalars(
            select(AuditLog).where(AuditLog.entity_id == cid, AuditLog.action == "UPLOAD")
        ).first()
        assert kayit is not None
    d = istemci.get("/api/audit", params={"limit": 200}).json()["entries"]
    giris = next(e for e in d if e["entity_id"] == cid and e["action"] == "UPLOAD")
    assert giris["detail_json"]["tur"] == "HIZMET"
    assert giris["detail_json"]["yayimlanmaz"] is True
    assert giris["detail_json"]["bayt"] > 0


# --------------------------------------------- motor künyesi: analysis_runs
def test_motor_kunyesi_kosu_satirina_donar(istemci):
    """Kural katmanıyla koşan analizde anahtar kaynağı 'yok' olmalı.

    Bu, 'model çağrılmadı' olgusunun kendisidir — eksik veri değil.
    """
    from app import runner

    r = istemci.post("/api/contracts",
                     files={"file": ("motor.txt", b"Madde 1. Deneme metni. " * 30)})
    cid = r.json()["contract_id"]
    for _ in range(80):
        if runner.progress(cid).get("status") in ("TAMAMLANDI", "HATA"):
            break
        import time; time.sleep(0.25)

    with session_scope() as s:
        k = s.scalars(
            select(AnalysisRun).where(AnalysisRun.contract_id == cid)
        ).first()
        assert k is not None, "koşu satırı yok"
        assert k.anahtar_kaynagi == "yok", (
            f"kural katmanı koşusunda anahtar kaynağı {k.anahtar_kaynagi!r}"
        )
        assert k.saglayici, "sağlayıcı adı yazılmadı"


# ------------------------------------------------------------------ künye
def test_kunye_dagilmis_olgulari_birlestirir(istemci):
    r = istemci.post("/api/contracts",
                     files={"file": ("kunye.txt", b"Madde 1. Deneme metni. " * 30)},
                     headers={"X-Forwarded-For": "198.51.100.7"})
    cid = r.json()["contract_id"]

    k = istemci.get(f"/api/contracts/{cid}/kunye")
    assert k.status_code == 200, k.text
    d = k.json()
    assert d["sozlesme"]["id"] == cid
    assert d["koken"]["ip"] == "198.51.100.7"
    assert isinstance(d["kosular"], list)
    assert "maliyet_usd" in d["kullanim"]
    assert any(o["eylem"] == "UPLOAD" for o in d["olaylar"]), "yükleme olayı künyede yok"


def test_kunye_silinmis_sozlesmeyi_gostermez(istemci):
    r = istemci.post("/api/contracts",
                     files={"file": ("silinen.txt", b"deneme metni " * 40)})
    cid = r.json()["contract_id"]
    istemci.delete(f"/api/contracts/{cid}")
    assert istemci.get(f"/api/contracts/{cid}/kunye").status_code == 404


# ----------------------------------------------------------- geri doldurma
def test_geri_doldurma_gecmisi_kendi_evine_tasir(istemci):
    """Kolon sonradan eklendi diye geçmiş boş kalmamalı.

    Bilgi kaybolmuş değil, başka tablolara dağılmış: yükleyen ve IP denetim
    izinde, model llm_calls'ta. Geri doldurma onları yerine taşır.
    """
    with session_scope() as s:
        c = Contract(title="eski", filename="eski.txt", contract_type="SAAS")
        s.add(c); s.flush(); cid = c.id
        s.add(AuditLog(user="ahmet", action="UPLOAD", entity_type="contract",
                       entity_id=cid, ip="203.0.113.44"))
        s.add(AnalysisRun(contract_id=cid, status="DONE"))
        for _ in range(3):
            s.add(LLMCall(contract_id=cid, model="qwen3.8-flash", input_tokens=10))

    geri_doldur()

    with session_scope() as s:
        c = s.get(Contract, cid)
        assert c.yukleyen == "ahmet", f"yükleyen doldurulmadı: {c.yukleyen!r}"
        assert c.yukleyen_ip == "203.0.113.44"
        kosu = s.scalars(
            select(AnalysisRun).where(AnalysisRun.contract_id == cid)
        ).first()
        assert kosu.model == "qwen3.8-flash", f"model doldurulmadı: {kosu.model!r}"
        assert kosu.anahtar_kaynagi == "sunucu", "LLM çağrısı varken 'sunucu' olmalıydı"


def test_geri_doldurma_dolu_degeri_ezmez(istemci):
    """Idempotent ve koruyucu: dolu alana dokunmaz."""
    with session_scope() as s:
        c = Contract(title="dolu", filename="dolu.txt", yukleyen="gercek-kullanici",
                     yukleyen_ip="10.1.1.1")
        s.add(c); s.flush(); cid = c.id
        s.add(AuditLog(user="baskasi", action="UPLOAD", entity_type="contract",
                       entity_id=cid, ip="203.0.113.99"))

    geri_doldur()
    geri_doldur()          # iki kez: idempotent olmalı

    with session_scope() as s:
        c = s.get(Contract, cid)
        assert c.yukleyen == "gercek-kullanici", "geri doldurma dolu değeri ezdi"
        assert c.yukleyen_ip == "10.1.1.1"


def test_geri_doldurma_llm_cagrisi_olmayani_yok_isaretler(istemci):
    """Çağrı yoksa analiz kural katmanıyla koşmuştur — bu bir olgudur."""
    with session_scope() as s:
        c = Contract(title="kuralli", filename="kuralli.txt")
        s.add(c); s.flush(); cid = c.id
        s.add(AnalysisRun(contract_id=cid, status="DONE"))

    geri_doldur()

    with session_scope() as s:
        k = s.scalars(
            select(AnalysisRun).where(AnalysisRun.contract_id == cid)
        ).first()
        assert k.anahtar_kaynagi == "yok"
