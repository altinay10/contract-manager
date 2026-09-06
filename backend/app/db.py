"""SQLAlchemy oturum yönetimi."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

log = logging.getLogger(__name__)

_COMMIT_DENEME = 8
_COMMIT_BEKLEME = 0.4

# Not: yazmalari surec ici bir kilitle siraya sokmak denendi ve GERI ALINDI.
# Kilidi tutan is parcacigi SQLite'in busy_timeout'unda beklerken digerleri
# kilidi bekliyor; iki bekleme ust uste binince analiz saatlerce takiliyor.
# Cakismayi yeniden deneme cozuyor, beklemeyi ise SQLite'in kendisi yonetiyor.

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Arka plan iş parçacığı aynı bağlantıyı kullanabilsin.
    _connect_args = {
        "check_same_thread": False,   # arka plan is parcaciklari icin
        "timeout": 30,                # SQLITE_BUSY beklemesi
    }

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
        # Kilit bekleme suresi baglanti basina burada da kurulur.
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _kilit_hatasi(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) and "database is locked" in str(exc).lower()


def commit_retry(s: Session) -> None:
    """Kilit çakışmasında üstel bekleyişle yeniden denenen commit.

    Uzun süren analiz, tek bir oturumu açık tutup aşama aşama commit eder;
    bu commit'ler session_scope'un dışındadır. Eşzamanlı analizlerde
    SQLITE_BUSY tam burada geliyor ve analiz thread'ini öldürüyordu.
    """
    for deneme in range(_COMMIT_DENEME):
        try:
            s.commit()
            return
        except OperationalError as exc:
            if not _kilit_hatasi(exc) or deneme == _COMMIT_DENEME - 1:
                raise
            s.rollback()
            time.sleep(_COMMIT_BEKLEME * (2 ** deneme))
            log.info("Veritabanı kilitli - commit yeniden deneniyor (%d)", deneme + 1)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit/rollback'i garanti eden oturum bağlamı.

    Commit, kilit çakışmasında sınırlı sayıda yeniden denenir. WAL ve
    busy_timeout tek başına yetmiyor: pysqlite işlemi ilk yazmaya kadar
    geciktirdiği için, önce okuyup sonra yazmaya yükselen bir işlem eşzamanlı
    bir yazar varken ANINDA SQLITE_BUSY alır — busy_timeout orada devreye
    girmez. Eşzamanlı iki analiz bu yüzden "database is locked" ile çöküyordu.

    İşlemin tamamını BEGIN IMMEDIATE ile açmak da çözüm değil: okuma
    işlemlerini de sıraya sokar ve iptal denetimi gibi ayrı oturum kullanan
    yerlerde kilitlenmeye yol açar. Bu yüzden yalnızca commit yeniden denenir.
    """
    s = SessionLocal()
    try:
        yield s
        commit_retry(s)
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@contextmanager
def read_session() -> Iterator[Session]:
    """Salt-okunur oturum: sonunda commit DEGIL rollback yapar.

    Iptal denetimi madde basina calisiyor ve session_scope uzerinden gidince
    her seferinde yazma yolunu (commit + kilit yeniden deneme) tetikliyordu.
    Okuma icin yazma niyeti bildirmenin anlami yok; es zamanli analizlerde
    bosuna cakisma uretiyordu.
    """
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
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
        "reports": {"comparison_id": "VARCHAR(32) DEFAULT ''"},
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
