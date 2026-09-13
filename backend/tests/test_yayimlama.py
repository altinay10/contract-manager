"""Sözleşme sonucunu yayımlama seçeneği.

Kutu işaretlenirse sözleşme aşağıdaki listeye ve portföy paneline DÜŞMEZ.
Bunun dışında hiçbir şey değişmez: analiz normal koşar, veritabanında hiçbir
satır eksilmez, denetim izi yazılmaya devam eder ve yükleyen kişi sonucu
elindeki kimlikle görmeye devam eder — bulgular, ilerleme, rapor.

Gizlilik yalnızca YAYIMLAMAYLA ilgilidir, erişimle değil: kimliği bilen
sonucu görür. Tehdit modeli güvenilir LAN (bkz. CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import engine, ensure_schema, session_scope
from app.main import app
from app.models import Base, Clause, Contract, Finding, Report


@pytest.fixture(scope="module")
def istemci():
    Base.metadata.create_all(engine)
    ensure_schema()
    with TestClient(app) as c:
        yield c


def _sozlesme(tmp_path: Path, gizli: bool) -> tuple[str, str]:
    """Maddesi, bulgusu, raporu ve diskte dosyası olan bir sözleşme."""
    yuklenen = tmp_path / f"s-{int(gizli)}.txt"
    yuklenen.write_text("Madde 1. Deneme metni.", encoding="utf-8")
    rapor_dosya = tmp_path / f"r-{int(gizli)}.json"
    rapor_dosya.write_text('{"x": 1}', encoding="utf-8")

    with session_scope() as s:
        c = Contract(title="deneme", filename=yuklenen.name, contract_type="SAAS",
                     storage_path=str(yuklenen), status="TAMAMLANDI",
                     risk_score=27.7, risk_band="KIRMIZI", listede_gizli=gizli)
        s.add(c)
        s.flush()
        cid = c.id
        s.add(Clause(contract_id=cid, number="1", text="Deneme metni.", order_index=0))
        s.add(Finding(contract_id=cid, code="TEST", severity="KRITIK", title="deneme"))
        r = Report(contract_id=cid, fmt="JSON", path=str(rapor_dosya),
                   filename=rapor_dosya.name, size_bytes=8)
        s.add(r)
        s.flush()
        rid = r.id
    return cid, rid


# --------------------------------------------------------------------------- #
def test_varsayilan_kapali_sozlesme_listelenir(istemci, tmp_path):
    """Kutu işaretlenmeyen sözleşme eskisi gibi görünür — mevcut davranış bozulmamalı."""
    cid, _ = _sozlesme(tmp_path, gizli=False)
    liste = istemci.get("/api/contracts").json()["contracts"]
    assert cid in [c["id"] for c in liste], "olağan sözleşme listeden düştü"
    panel = istemci.get("/api/dashboard").json()["sozlesmeler"]
    assert cid in [c["id"] for c in panel], "olağan sözleşme panelden düştü"


def test_gizli_sozlesme_listede_ve_panelde_gorunmez(istemci, tmp_path):
    cid, _ = _sozlesme(tmp_path, gizli=True)
    liste = istemci.get("/api/contracts").json()["contracts"]
    assert cid not in [c["id"] for c in liste], "gizli sözleşme listede"
    panel = istemci.get("/api/dashboard").json()["sozlesmeler"]
    assert cid not in [c["id"] for c in panel], "gizli sözleşme panelde"


def test_gizli_sozlesmenin_bulgusu_ozet_sayilarina_girmez(istemci, tmp_path):
    """Bulgular süzülmezse sözleşme dolaylı olarak yayımlanmış olur.

    Özet sayıları ve "en sık ihlal" sıralaması gizli sözleşmenin bulgularını
    yansıtırsa, satır görünmese de içeriği dışarı sızar.
    """
    once = istemci.get("/api/dashboard").json()["ozet"]["toplam_bulgu"]
    _sozlesme(tmp_path, gizli=True)
    sonra = istemci.get("/api/dashboard").json()["ozet"]["toplam_bulgu"]
    assert sonra == once, f"gizli sözleşmenin bulgusu özete girdi ({once} -> {sonra})"


def test_gizli_sozlesme_kimlikle_erisilebilir_kalir(istemci, tmp_path):
    """Yayımlanmamak erişilmez olmak değil: yükleyen kişi sonucunu görmeye devam eder."""
    cid, rid = _sozlesme(tmp_path, gizli=True)
    assert istemci.get(f"/api/contracts/{cid}/findings").json()["count"] == 1
    assert istemci.get(f"/api/contracts/{cid}/progress").status_code == 200
    assert istemci.get(f"/api/contracts/{cid}/usage").status_code == 200
    assert istemci.get(f"/api/reports/{rid}").status_code == 200, "raporu indirilemiyor"


def test_gizli_sozlesme_veritabaninda_durur(istemci, tmp_path):
    """Yayımlamamak silmek değildir: hiçbir satır eksilmez, dosya kalır."""
    cid, rid = _sozlesme(tmp_path, gizli=True)
    with session_scope() as s:
        c = s.get(Contract, cid)
        assert c is not None, "sözleşme satırı düştü"
        assert c.silindi_at is None, "yayımlamama silme damgası koydu"
        assert Path(c.storage_path).exists(), "yüklenen dosya diskten silindi"
        assert len(list(s.scalars(
            Finding.__table__.select().where(Finding.contract_id == cid)))) == 1
        assert s.get(Report, rid) is not None, "rapor satırı düştü"


def test_yukleme_ucu_bayragi_kaydeder(istemci):
    """Arayüzden gelen form alanı satıra yazılmalı."""
    r = istemci.post("/api/contracts",
                     files={"file": ("gizli.txt", b"deneme metni " * 40)},
                     data={"listede_gizli": "true"})
    assert r.status_code < 400, r.text
    with session_scope() as s:
        assert s.get(Contract, r.json()["contract_id"]).listede_gizli is True

    r = istemci.post("/api/contracts",
                     files={"file": ("acik.txt", b"deneme metni " * 40)})
    assert r.status_code < 400
    with session_scope() as s:
        assert s.get(Contract, r.json()["contract_id"]).listede_gizli is False, (
            "alan gönderilmediğinde varsayılan yayımla olmalı"
        )
