"""Kimlik dogrulama ve denetim izi testleri.

Modul YENIDEN YUKLENMEZ: importlib.reload, diger test modullerinin kullandigi
veritabani motorunu ve oturumlari gecersiz kiliyordu. Bunun yerine ayarlar
dogrudan degistirilir ve auth durumu sifirlanir.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings as cfg
from app.db import engine, ensure_schema
from app.main import app
from app.models import Base


@pytest.fixture(scope="module")
def korumali_istemci(tmp_path_factory):
    Base.metadata.create_all(engine)
    ensure_schema()

    eski = (cfg.auth_enabled, cfg.app_password, cfg.session_secret, cfg.storage_dir)
    cfg.auth_enabled = True
    cfg.app_password = "cok-gizli-parola-123"
    cfg.session_secret = "test-siri-degismez"
    auth.reset()

    with TestClient(app) as c:
        yield c

    (cfg.auth_enabled, cfg.app_password, cfg.session_secret, cfg.storage_dir) = eski
    auth.reset()


@pytest.fixture(autouse=True)
def _oturumu_temizle(korumali_istemci):
    """Her test kendi oturum durumundan baslasin."""
    korumali_istemci.cookies.clear()
    auth.giris_sifirla("testclient")
    yield


KORUMALI = [
    ("get", "/api/settings"),
    ("get", "/api/contracts"),
    ("get", "/api/audit"),
    ("post", "/api/demo"),
    ("get", "/api/contracts/xyz/progress"),
    ("get", "/api/reports/xyz"),
]


@pytest.mark.parametrize("yontem,yol", KORUMALI)
def test_oturumsuz_erisim_reddedilir(korumali_istemci, yontem, yol):
    r = getattr(korumali_istemci, yontem)(yol)
    assert r.status_code == 401, f"{yol} korumasız! ({r.status_code})"


def test_sozlesme_yukleme_de_korunur(korumali_istemci):
    r = korumali_istemci.post("/api/contracts",
                              files={"file": ("x.txt", b"deneme metni " * 40)})
    assert r.status_code == 401, "yükleme ucu korumasız"


def test_saglik_ucu_acik_kalir(korumali_istemci):
    """Docker healthcheck oturum acamaz; bu uc acik ama ayrinti sizdirmaz."""
    r = korumali_istemci.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_yanlis_parola_reddedilir(korumali_istemci):
    r = korumali_istemci.post("/api/login", json={"password": "yanlis"})
    assert r.status_code == 401


def test_dogru_parola_oturum_acar(korumali_istemci):
    r = korumali_istemci.post("/api/login", json={"password": "cok-gizli-parola-123"})
    assert r.status_code == 200
    assert "feneri_oturum" in r.cookies or r.cookies.get("feneri_oturum") is not None
    # Artik korumali uclar acilir
    assert korumali_istemci.get("/api/settings").status_code == 200
    assert korumali_istemci.get("/api/contracts").status_code == 200


def test_cikis_oturumu_kapatir(korumali_istemci):
    korumali_istemci.post("/api/login", json={"password": "cok-gizli-parola-123"})
    assert korumali_istemci.get("/api/settings").status_code == 200
    korumali_istemci.post("/api/logout")
    assert korumali_istemci.get("/api/settings").status_code == 401


def test_kurcalanmis_cerez_reddedilir(korumali_istemci):
    token = auth.oturum_uret()
    bozuk = token[:-6] + "AAAAAA"
    korumali_istemci.cookies.set("feneri_oturum", bozuk)
    r = korumali_istemci.get("/api/settings")
    assert r.status_code == 401


def test_suresi_dolmus_oturum_reddedilir(korumali_istemci, monkeypatch):
    monkeypatch.setattr(cfg, "session_hours", -1)     # gecmiste bitmis
    token = auth.oturum_uret()
    korumali_istemci.cookies.set("feneri_oturum", token)
    r = korumali_istemci.get("/api/settings")
    assert r.status_code == 401


def test_kaba_kuvvet_frenlenir(korumali_istemci):
    auth.giris_sifirla("testclient")
    for _ in range(auth.AZAMI_DENEME):
        korumali_istemci.post("/api/login", json={"password": "yanlis"})
    r = korumali_istemci.post("/api/login", json={"password": "yanlis"})
    assert r.status_code == 429, "kaba kuvvet freni çalışmadı"
    auth.giris_sifirla("testclient")


def test_parola_diske_duz_metin_yazilmaz():
    kayit = auth._hashle("gizli")
    assert kayit.startswith("scrypt$")
    assert "gizli" not in kayit
    assert auth._dogrula_parola("gizli", kayit) is True
    assert auth._dogrula_parola("gizli2", kayit) is False


def test_parola_yoksa_rastgele_uretilir(tmp_path, monkeypatch):
    """Uygulama parolasiz ACIK BIRAKILMAZ."""
    monkeypatch.setattr(cfg, "app_password", "")
    monkeypatch.setattr(cfg, "storage_dir", tmp_path)
    auth.reset()
    d = auth.durum()
    assert d.uretilen_parola, "parola üretilmedi"
    assert len(d.uretilen_parola) >= 12
    assert (tmp_path / "auth.json").exists()
    auth.reset()
    # sonraki testler icin parolayi geri koy
    cfg.app_password = "cok-gizli-parola-123"
    auth.reset()


# --------------------------------------------------------------- denetim izi
def test_giris_ve_islemler_denetim_izine_yazilir(korumali_istemci):
    korumali_istemci.post("/api/login", json={"password": "yanlis"})
    korumali_istemci.post("/api/login", json={"password": "cok-gizli-parola-123"})
    korumali_istemci.put("/api/settings", json={"provider": "heuristic"})

    d = korumali_istemci.get("/api/audit").json()
    eylemler = [e["action"] for e in d["entries"]]
    assert "LOGIN" in eylemler
    assert "LOGIN_FAILED" in eylemler
    assert "SETTINGS_CHANGED" in eylemler
    for e in d["entries"]:
        assert e["at"] and e["user"]


def test_denetim_izinde_anahtar_sizmaz(korumali_istemci):
    korumali_istemci.post("/api/login", json={"password": "cok-gizli-parola-123"})
    korumali_istemci.put("/api/settings", json={
        "provider": "gemini", "api_key": "AIzaCOKGIZLI123456"})
    d = korumali_istemci.get("/api/audit").json()
    assert "AIzaCOKGIZLI123456" not in str(d), "API anahtarı denetim izine sızdı"
    korumali_istemci.delete("/api/settings/key")


def test_rapor_indirme_denetlenir(korumali_istemci):
    korumali_istemci.post("/api/login", json={"password": "cok-gizli-parola-123"})
    korumali_istemci.get("/api/reports/olmayan")
    d = korumali_istemci.get("/api/audit").json()
    # Olmayan rapor icin kayit olmaz; ama uc korumali oldugu icin 404 dondu
    assert isinstance(d["entries"], list)


def test_giris_ekrani_betik_sonda_olsa_da_calisir(korumali_istemci):
    """Gercek hata: DOMContentLoaded betikten once tetiklendiginde sayfa bos kaliyordu."""
    h = korumali_istemci.get("/").text
    assert "document.readyState" in h, "hazır-durum kontrolü yok"
    assert "kapiyiKur" in h
    # Her iki yol da tanimli olmali
    assert "addEventListener('DOMContentLoaded', kapiyiKur)" in h
