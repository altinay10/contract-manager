"""Silme ve saklama suresi — VERI KAYBI OLMADIGININ testi.

Bu dosyanin tek isi su: silme yumusaktir. Damga konar, sozlesme disariya
gorunmez olur, ama hicbir satir veritabanindan dusmez ve hicbir dosya diskten
kaldirilmaz. Islem geri alinabilir.

`contracts` satiri dusurulurse `reports`, `llm_calls`, `work_items` ve
`dropped_findings` sessizce oksuz kalir — o tablolarin `contract_id` alani
yabanci anahtar degil. Kalici silme bu yuzden bilincli olarak uygulanmadi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import runner
from app.config import settings as cfg
from app.db import engine, ensure_schema, session_scope
from app.main import app
from app.models import Base, Clause, Contract, Finding, Report


@pytest.fixture(scope="module")
def istemci():
    Base.metadata.create_all(engine)
    ensure_schema()
    with TestClient(app) as c:
        yield c


def _dolu_sozlesme(tmp_path: Path, yas_gun: int = 0) -> tuple[str, str, str]:
    """Maddesi, bulgusu, raporu ve diskte dosyasi olan bir sozlesme uretir."""
    yuklenen = tmp_path / "sozlesme.txt"
    yuklenen.write_text("Madde 1. Deneme metni.", encoding="utf-8")
    rapor_dosya = tmp_path / "rapor.json"
    rapor_dosya.write_text('{"x": 1}', encoding="utf-8")

    with session_scope() as s:
        c = Contract(title="dolu", filename="sozlesme.txt", contract_type="SAAS",
                     storage_path=str(yuklenen), status="TAMAMLANDI",
                     risk_score=27.7, risk_band="KIRMIZI")
        if yas_gun:
            c.created_at = datetime.now(timezone.utc) - timedelta(days=yas_gun)
        s.add(c)
        s.flush()
        cid = c.id
        s.add(Clause(contract_id=cid, number="1", text="Deneme metni.", order_index=0))
        s.add(Finding(contract_id=cid, code="TEST", severity="KRITIK", title="deneme"))
        r = Report(contract_id=cid, fmt="JSON", path=str(rapor_dosya),
                   filename="rapor.json", size_bytes=8)
        s.add(r)
        s.flush()
        rid = r.id
    return cid, rid, str(yuklenen)


def _sayimlar(cid: str) -> dict[str, int]:
    with session_scope() as s:
        return {
            "contracts": len([x for x in s.scalars(
                Contract.__table__.select().where(Contract.id == cid))]),
            "clauses": len(list(s.scalars(
                Clause.__table__.select().where(Clause.contract_id == cid)))),
            "findings": len(list(s.scalars(
                Finding.__table__.select().where(Finding.contract_id == cid)))),
            "reports": len(list(s.scalars(
                Report.__table__.select().where(Report.contract_id == cid)))),
        }


# --------------------------------------------------------------------------- #
def test_silme_hicbir_veriyi_dusurmez(istemci, tmp_path):
    """En onemli test: silme sonrasi tum satirlar ve dosyalar yerinde."""
    cid, rid, yuklenen = _dolu_sozlesme(tmp_path)
    once = _sayimlar(cid)
    assert once == {"contracts": 1, "clauses": 1, "findings": 1, "reports": 1}

    r = istemci.delete(f"/api/contracts/{cid}")
    assert r.status_code == 200, r.text
    assert r.json()["geri_alinabilir"] is True

    sonra = _sayimlar(cid)
    assert sonra == once, f"silme satir dusurdu: {once} -> {sonra}"
    assert Path(yuklenen).exists(), "yuklenen dosya diskten silindi"
    with session_scope() as s:
        assert s.get(Report, rid) is not None, "rapor satiri dustu"
        assert Path(s.get(Report, rid).path).exists(), "rapor dosyasi diskten silindi"
        assert s.get(Contract, cid).silindi_at is not None, "silme damgasi konmadi"


def test_silinen_sozlesme_disariya_gorunmez(istemci, tmp_path):
    cid, rid, _ = _dolu_sozlesme(tmp_path)
    istemci.delete(f"/api/contracts/{cid}")

    liste = istemci.get("/api/contracts").json()["contracts"]
    assert cid not in [c["id"] for c in liste], "silinen sozlesme listede"
    assert istemci.get(f"/api/contracts/{cid}/findings").status_code == 404
    assert istemci.get(f"/api/contracts/{cid}/progress").status_code == 404
    assert istemci.get(f"/api/contracts/{cid}/usage").status_code == 404
    assert istemci.get(f"/api/reports/{rid}").status_code == 404, (
        "silinen sozlesmenin raporu hala indirilebiliyor"
    )


def test_silinen_sozlesme_panelden_de_duser(istemci, tmp_path):
    """Portfoy paneli ayri bir sorgu kullanir; suzgec orada da olmali.

    Bulgular da suzulmeli, yoksa silinen sozlesmenin bulgulari ozet
    sayilarinda ve "en sik ihlal" siralamasinda gorunmeye devam eder.
    """
    cid, _, _ = _dolu_sozlesme(tmp_path)
    once = istemci.get("/api/dashboard").json()
    assert cid in [x["id"] for x in once["sozlesmeler"]]

    istemci.delete(f"/api/contracts/{cid}")
    sonra = istemci.get("/api/dashboard").json()
    assert cid not in [x["id"] for x in sonra["sozlesmeler"]], "silinen sozlesme panelde"
    assert sonra["ozet"]["toplam_bulgu"] == once["ozet"]["toplam_bulgu"] - 1, (
        "silinen sozlesmenin bulgusu ozet sayisinda kaldi"
    )


def test_silinenler_listelenir_ve_geri_alinir(istemci, tmp_path):
    """Yumusak silme tek yonlu olmamali: kimlik bilinmese de geri alinabilmeli."""
    cid, rid, _ = _dolu_sozlesme(tmp_path)
    istemci.delete(f"/api/contracts/{cid}")

    silinmisler = istemci.get("/api/contracts/silinmisler").json()["contracts"]
    kayit = next((c for c in silinmisler if c["id"] == cid), None)
    assert kayit is not None, "silinen sozlesme silinmisler listesinde yok"
    assert kayit["silindi_at"], "silme damgasi bildirilmiyor"

    r = istemci.post(f"/api/contracts/{cid}/restore")
    assert r.status_code == 200
    assert r.json()["silindi"] is False

    liste = istemci.get("/api/contracts").json()["contracts"]
    assert cid in [c["id"] for c in liste], "geri alinan sozlesme listeye donmedi"
    assert istemci.get(f"/api/contracts/{cid}/findings").json()["count"] == 1
    assert istemci.get(f"/api/reports/{rid}").status_code == 200, (
        "geri alinan sozlesmenin raporu indirilemiyor"
    )


def test_silinmis_sozlesme_yeniden_silinmez(istemci, tmp_path):
    cid, _, _ = _dolu_sozlesme(tmp_path)
    assert istemci.delete(f"/api/contracts/{cid}").status_code == 200
    assert istemci.delete(f"/api/contracts/{cid}").status_code == 404


# --------------------------------------------------------------- saklama suresi
def test_saklama_suresi_varsayilan_kapali(istemci, tmp_path, monkeypatch):
    """RETENTION_DAYS=0 hicbir seye dokunmaz — varsayilan bu."""
    cid, _, _ = _dolu_sozlesme(tmp_path, yas_gun=400)
    monkeypatch.setattr(cfg, "retention_days", 0)

    assert runner.apply_retention() == 0
    with session_scope() as s:
        assert s.get(Contract, cid).silindi_at is None, "kapali saklama suresi sildi"


def test_saklama_suresi_isaretler_ama_silmez(istemci, tmp_path, monkeypatch):
    """Yasi gecen sozlesme isaretlenir; satirlar ve dosyalar yerinde kalir."""
    cid, rid, yuklenen = _dolu_sozlesme(tmp_path, yas_gun=40)
    once = _sayimlar(cid)
    monkeypatch.setattr(cfg, "retention_days", 30)

    assert runner.apply_retention() >= 1
    with session_scope() as s:
        assert s.get(Contract, cid).silindi_at is not None, "yasi gecen sozlesme isaretlenmedi"

    assert _sayimlar(cid) == once, "saklama suresi satir dusurdu"
    assert Path(yuklenen).exists(), "saklama suresi dosyayi diskten sildi"

    # Otomatik islem de geri alinabilir olmali.
    assert istemci.post(f"/api/contracts/{cid}/restore").status_code == 200
    with session_scope() as s:
        assert s.get(Contract, cid).silindi_at is None


def test_saklama_suresi_genc_sozlesmeye_dokunmaz(istemci, tmp_path, monkeypatch):
    cid, _, _ = _dolu_sozlesme(tmp_path, yas_gun=5)
    monkeypatch.setattr(cfg, "retention_days", 30)
    runner.apply_retention()
    with session_scope() as s:
        assert s.get(Contract, cid).silindi_at is None, "genc sozlesme silindi"
