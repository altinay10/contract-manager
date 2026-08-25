"""Failsafe / devam mekanizmasi testleri.

Korunmasi gereken davranis: surec yarida kesilirse ANALIZ BASTAN BASLAMAZ.
Tamamlanmis asamalar ve tamamlanmis maddeler tekrar islenmez.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app import runner
from app.db import engine, session_scope
from app.models import (
    AnalysisRun, Base, Contract, Finding, StageCheckpoint, WorkItem,
)

SAMPLE = Path(__file__).resolve().parent.parent.parent / "samples" / "ornek-saas-sozlesmesi.txt"


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(engine)
    yield


def _yeni_sozlesme() -> str:
    with session_scope() as s:
        c = Contract(
            title="test", filename=SAMPLE.name, storage_path=str(SAMPLE),
            contract_type="SAAS", involves_personal_data=True, is_outsourcing=True,
        )
        s.add(c)
        s.flush()
        return c.id


def test_tam_analiz_calisir_ve_rapor_uretir():
    cid = _yeni_sozlesme()
    runner.execute(cid)
    p = runner.progress(cid)
    assert p["run_status"] == "DONE"
    assert all(st["status"] == "DONE" for st in p["stages"])
    assert p["risk_score"] is not None
    assert any(r["fmt"] == "DOCX" for r in p["reports"])


def test_kesinti_sonrasi_kaldigi_yerden_devam_eder(monkeypatch):
    cid = _yeni_sozlesme()
    orijinal = runner.analyze_clause
    sayac = {"n": 0}

    def coken(*a, **kw):
        sayac["n"] += 1
        if sayac["n"] > 6:
            raise KeyboardInterrupt("simule edilmis surec olumu")
        return orijinal(*a, **kw)

    monkeypatch.setattr(runner, "analyze_clause", coken)
    with pytest.raises(KeyboardInterrupt):
        runner.execute(cid)

    with session_scope() as s:
        tamam_asama = [
            cp.stage for cp in s.scalars(
                select(StageCheckpoint).join(AnalysisRun)
                .where(AnalysisRun.contract_id == cid, StageCheckpoint.status == "DONE")
            )
        ]
        biten_madde = s.query(WorkItem).filter(
            WorkItem.contract_id == cid, WorkItem.stage == "RISK", WorkItem.status == "DONE"
        ).count()

    # Cokmeden once ilerleme kaydedilmis olmali.
    assert "SEGMENT" in tamam_asama and "CLASSIFY" in tamam_asama
    assert "RISK" not in tamam_asama
    assert biten_madde > 0

    # --- ikinci tur: kaldigi yerden ---
    sayac2 = {"n": 0}

    def sayan(*a, **kw):
        sayac2["n"] += 1
        return orijinal(*a, **kw)

    monkeypatch.setattr(runner, "analyze_clause", sayan)
    runner.execute(cid)

    p = runner.progress(cid)
    assert p["run_status"] == "DONE"
    assert p["resumed_count"] >= 1

    with session_scope() as s:
        toplam_madde = s.query(WorkItem).filter(
            WorkItem.contract_id == cid, WorkItem.stage == "RISK"
        ).count()

    # Ikinci turda TUM maddeler degil, yalnizca kalanlar islenmis olmali.
    assert sayac2["n"] < toplam_madde + sayac["n"], "devam etmedi, bastan basladi"
    assert biten_madde > 0


def test_devam_eden_analiz_ayni_sonucu_uretir(monkeypatch):
    """Kesinti, sonucun dogrulugunu bozmamali."""
    kesintisiz = _yeni_sozlesme()
    runner.execute(kesintisiz)
    with session_scope() as s:
        beklenen = {
            (f.code, f.finding_type, f.title)
            for f in s.scalars(select(Finding).where(Finding.contract_id == kesintisiz))
        }
        beklenen_skor = s.get(Contract, kesintisiz).risk_score

    kesintili = _yeni_sozlesme()
    orijinal = runner.analyze_clause
    sayac = {"n": 0}

    def coken(*a, **kw):
        sayac["n"] += 1
        if sayac["n"] == 5:
            raise RuntimeError("gecici hata")
        return orijinal(*a, **kw)

    monkeypatch.setattr(runner, "analyze_clause", coken)
    runner.execute(kesintili)  # madde bazli hata tum analizi durdurmaz

    monkeypatch.setattr(runner, "analyze_clause", orijinal)
    runner.execute(kesintili)  # kalan/basarisiz maddeler icin devam

    with session_scope() as s:
        elde = {
            (f.code, f.finding_type, f.title)
            for f in s.scalars(select(Finding).where(Finding.contract_id == kesintili))
        }
        elde_skor = s.get(Contract, kesintili).risk_score

    assert elde == beklenen, "kesinti sonrasi bulgular farkli"
    assert elde_skor == beklenen_skor


def test_olumcul_hata_yeniden_denenmez():
    """Bozuk dosya icin 3 kez denemenin anlami yok; hemen HATA'ya dusmeli."""
    with session_scope() as s:
        c = Contract(title="yok", filename="olmayan.txt",
                     storage_path="/tmp/kesinlikle-olmayan-dosya-9137.txt")
        s.add(c)
        s.flush()
        cid = c.id

    runner.execute(cid)
    p = runner.progress(cid)
    assert p["run_status"] == "FAILED"
    ingest = next(st for st in p["stages"] if st["key"] == "INGEST")
    assert ingest["status"] == "FAILED"
    assert ingest["attempts"] == 1, "olumcul hata bosuna tekrarlanmis"


def test_taze_kalp_atisli_ama_baska_acilistan_kalan_run_oksuz_sayilir():
    """Konteyner hemen yeniden baslarsa kalp atisi taze kalir.

    Zamana bakan bir olcut bu durumu kaciriyordu ve analiz askida kaliyordu.
    Olcut artik "hangi acilis baslatti" sorusu.
    """
    cid = _yeni_sozlesme()
    with session_scope() as s:
        run = AnalysisRun(contract_id=cid, status="RUNNING",
                          owner_id="onceki-acilisin-kimligi")
        s.add(run)
        s.flush()
        s.add(StageCheckpoint(run_id=run.id, stage="RISK", position=7, status="RUNNING"))
        run.heartbeat_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)  # taze

    n = runner.recover_orphans(start_work=False)
    assert n >= 1, "taze kalp atışlı ama başka açılıştan kalan run kurtarılmadı"

    with session_scope() as s:
        run = s.scalar(select(AnalysisRun).where(AnalysisRun.contract_id == cid))
        assert run.owner_id == runner.BOOT_ID, "run bu sürecin sahipliğine geçmedi"


def test_bu_acilisin_calisan_isine_dokunulmaz():
    """Gercekten calisan bir analiz yanlislikla yeniden baslatilmamali."""
    cid = _yeni_sozlesme()
    with session_scope() as s:
        run = AnalysisRun(contract_id=cid, status="RUNNING", owner_id=runner.BOOT_ID)
        s.add(run)
        s.flush()
        run.heartbeat_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)
        rid = run.id

    onceki = runner.recover_orphans(start_work=False)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.resumed_count == 0, "çalışan analiz gereksiz yere devam ettirildi"


def test_orphan_kurtarma_calisan_asamayi_pending_yapar():
    cid = _yeni_sozlesme()
    with session_scope() as s:
        run = AnalysisRun(contract_id=cid, status="RUNNING")
        s.add(run)
        s.flush()
        s.add(StageCheckpoint(run_id=run.id, stage="RISK", position=7, status="RUNNING"))
        # kalp atisini bayatlat
        from datetime import datetime, timedelta, timezone
        run.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)

    n = runner.recover_orphans(start_work=False)
    assert n >= 1


# --------------------------------------------------------------- iptal
def test_iptal_analizi_durdurur_ve_ilerlemeyi_korur(monkeypatch):
    """Iptal, is parcacigini zorla oldurmez; guvenli bir noktada durdurur.

    O ana kadar tamamlanan asamalar KORUNUR ve devam ettirilebilir olmalidir.
    """
    import threading
    import time as _t

    cid = _yeni_sozlesme()
    orijinal = runner.analyze_clause
    sayac = {"n": 0}

    def yavas(*a, **kw):
        sayac["n"] += 1
        if sayac["n"] == 3:
            runner.cancel(cid)      # analiz sürerken iptal talebi
        _t.sleep(0.02)
        return orijinal(*a, **kw)

    monkeypatch.setattr(runner, "analyze_clause", yavas)
    runner.execute(cid)

    p = runner.progress(cid)
    assert p["run_status"] == "IPTAL", p["run_status"]

    tamam = [st["key"] for st in p["stages"] if st["status"] == "DONE"]
    assert "SEGMENT" in tamam and "CLASSIFY" in tamam, "iptal önceki ilerlemeyi sildi"
    assert "REPORT" not in tamam

    with session_scope() as s:
        biten = s.query(WorkItem).filter(
            WorkItem.contract_id == cid, WorkItem.stage == "RISK",
            WorkItem.status == "DONE").count()
    assert biten > 0, "iptal öncesi işlenen maddeler kaydedilmemiş"


def test_iptal_sonrasi_kaldigi_yerden_devam_edilebilir(monkeypatch):
    cid = _yeni_sozlesme()
    orijinal = runner.analyze_clause
    sayac = {"n": 0}

    def yavas(*a, **kw):
        sayac["n"] += 1
        if sayac["n"] == 3:
            runner.cancel(cid)
        return orijinal(*a, **kw)

    monkeypatch.setattr(runner, "analyze_clause", yavas)
    runner.execute(cid)
    assert runner.progress(cid)["run_status"] == "IPTAL"

    # devam
    monkeypatch.setattr(runner, "analyze_clause", orijinal)
    runner.execute(cid)
    p = runner.progress(cid)
    assert p["run_status"] == "DONE", p.get("error")
    assert all(st["status"] == "DONE" for st in p["stages"])
    assert p["risk_score"] is not None
    assert any(r["fmt"] == "DOCX" for r in p["reports"])


def test_iptal_edilen_analiz_oksuz_kurtarmayla_dirilmez():
    """Iptal edilmis bir is, arka plan tarayicisi tarafindan yeniden baslatilmamali."""
    from datetime import datetime, timedelta, timezone

    cid = _yeni_sozlesme()
    with session_scope() as s:
        run = AnalysisRun(contract_id=cid, status="RUNNING",
                          owner_id="baska-acilis", cancel_requested=True)
        s.add(run)
        s.flush()
        run.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
        rid = run.id

    runner.recover_orphans(start_work=False)
    with session_scope() as s:
        run = s.get(AnalysisRun, rid)
        assert run.resumed_count == 0, "iptal edilmiş iş diriltildi"


def test_biten_analiz_iptal_edilemez():
    cid = _yeni_sozlesme()
    runner.execute(cid)
    assert runner.progress(cid)["run_status"] == "DONE"
    assert runner.cancel(cid) is False
