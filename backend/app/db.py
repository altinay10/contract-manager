"""SQLAlchemy oturum yönetimi."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Arka plan iş parçacığı aynı bağlantıyı kullanabilsin.
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _):  # pragma: no cover - altyapı
        cur = dbapi_conn.cursor()
        # WAL: yazma sürerken okuma engellenmez -> ilerleme sorgusu analizi bloklamaz.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit/rollback'i garanti eden oturum bağlamı."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def ensure_schema() -> None:
    """Alembic devreye girene kadar: eksik kolonlari sessizce ekler.

    Konteyner birimindeki mevcut veritabani, kod guncellendiginde veri
    kaybetmeden uyumlu kalsin diye.
    """
    from sqlalchemy import inspect, text

    beklenen = {
        "analysis_runs": {"owner_id": "VARCHAR(32) DEFAULT ''",
                          "cancel_requested": "BOOLEAN DEFAULT 0"},
        "findings": {"quote_is_evidence": "BOOLEAN DEFAULT 1"},
        "contracts": {"model_izinli": "BOOLEAN DEFAULT 0"},
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for tablo, kolonlar in beklenen.items():
            if tablo not in insp.get_table_names():
                continue
            mevcut = {c["name"] for c in insp.get_columns(tablo)}
            for ad, tanim in kolonlar.items():
                if ad not in mevcut:
                    conn.execute(text(f"ALTER TABLE {tablo} ADD COLUMN {ad} {tanim}"))
