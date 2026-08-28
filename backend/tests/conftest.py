import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Testler gercek veritabanina dokunmasin.
_tmp = tempfile.mkdtemp(prefix="feneri-test-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("LLM_PROVIDER", "heuristic")
# Periyodik öksüz tarayıcı testlerde kapalı: arka planda çalışıp diğer testlerin
# veritabanı durumunu değiştiriyor ve testleri kararsız hale getiriyordu.
os.environ.setdefault("SWEEPER_ENABLED", "0")
# Mevcut testler is mantigina odaklanir; kimlik dogrulama ayri dosyada test edilir.
os.environ.setdefault("AUTH_ENABLED", "0")


import pytest


@pytest.fixture(autouse=True)
def _temiz_ayarlar():
    """Her testten sonra çalışma zamanı ayarlarını sıfırla.

    Aksi hâlde bir testte kaydedilen sahte API anahtarı sonraki testlerde
    sağlayıcıyı değiştirir ve testler birbirini etkiler.
    """
    yield
    try:
        from app import runtime_settings as rt
        from app.llm import provider as prov
        yol = rt._yol()
        if yol.exists():
            yol.unlink()
        rt.reset_cache()
        prov.reset_provider()
    except Exception:
        pass
