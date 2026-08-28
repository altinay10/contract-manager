"""Kimlik dogrulama — parola + imzali oturum cerezi.

Tasarim kararlari:
  * Ek bagimlilik yok: parola karmasi `hashlib.scrypt`, cerez imzasi `hmac`.
  * Parola tanimli degilse UYGULAMA ACIK KALMAZ: rastgele bir parola uretilir,
    aciliste loga basilir ve karmasi diske yazilir.
  * Oturum sunucuda tutulmaz; cerez imzalidir (kullanici + son kullanma).
    Sir degisirse tum oturumlar duser.
  * Giris denemeleri IP basina sinirlidir (kaba kuvvet frenlemesi).

Bu, tek kullanicili / kapali ag kurulumu icindir. Kurumsal SSO (OIDC) icin
`require_user` bagimliligini degistirmek yeterlidir; uc noktalar degismez.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException, Request

from .config import settings

log = logging.getLogger(__name__)

CEREZ_ADI = "feneri_oturum"
_lock = threading.Lock()
_durum: "AuthDurum | None" = None

# IP basina giris denemesi: (zaman damgalari)
_denemeler: dict[str, list[float]] = {}
AZAMI_DENEME = 8
PENCERE_SN = 300


@dataclass
class AuthDurum:
    parola_hash: str          # scrypt$tuz$karma
    secret: str               # cerez imza siri
    uretilen_parola: str = ""  # yalnizca ilk acilista loglanir


def _yol() -> Path:
    return settings.storage_dir / "auth.json"


def _hashle(parola: str, tuz: bytes | None = None) -> str:
    tuz = tuz or os.urandom(16)
    karma = hashlib.scrypt(parola.encode("utf-8"), salt=tuz, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(tuz).decode()}${base64.b64encode(karma).decode()}"


def _dogrula_parola(parola: str, kayit: str) -> bool:
    try:
        _, tuz_b64, karma_b64 = kayit.split("$")
        tuz = base64.b64decode(tuz_b64)
        beklenen = base64.b64decode(karma_b64)
    except Exception:
        return False
    karma = hashlib.scrypt(parola.encode("utf-8"), salt=tuz, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(karma, beklenen)


def durum() -> AuthDurum:
    global _durum
    with _lock:
        if _durum is not None:
            return _durum

        p = _yol()
        kayitli = {}
        if p.exists():
            try:
                kayitli = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("auth.json okunamadı (%s); yeniden oluşturuluyor", exc)

        secret = settings.session_secret or kayitli.get("secret") or secrets.token_urlsafe(32)
        uretilen = ""

        if settings.app_password:
            parola_hash = _hashle(settings.app_password)     # ortam degiskeni onceliklidir
        elif kayitli.get("password_hash"):
            parola_hash = kayitli["password_hash"]
        else:
            # Parola yoksa uygulama ACIK BIRAKILMAZ: rastgele parola uretilir.
            uretilen = secrets.token_urlsafe(12)
            parola_hash = _hashle(uretilen)

        _durum = AuthDurum(parola_hash=parola_hash, secret=secret, uretilen_parola=uretilen)

        if not settings.app_password:
            p.parent.mkdir(parents=True, exist_ok=True)
            gecici = p.with_suffix(".tmp")
            gecici.write_text(json.dumps({"password_hash": parola_hash, "secret": secret}),
                              encoding="utf-8")
            try:
                os.chmod(gecici, 0o600)
            except OSError:
                pass
            gecici.replace(p)
        return _durum


def reset() -> None:
    global _durum
    with _lock:
        _durum = None
    _denemeler.clear()


def parola_degistir(yeni: str) -> None:
    d = durum()
    with _lock:
        d.parola_hash = _hashle(yeni)
        d.uretilen_parola = ""
        p = _yol()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"password_hash": d.parola_hash, "secret": d.secret}),
                     encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
def oturum_uret(kullanici: str = "kullanici") -> str:
    d = durum()
    son = int(time.time()) + settings.session_hours * 3600
    govde = f"{kullanici}|{son}"
    imza = hmac.new(d.secret.encode(), govde.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{govde}|{imza}".encode()).decode()


def oturum_coz(token: str) -> str | None:
    try:
        ham = base64.urlsafe_b64decode(token.encode()).decode()
        kullanici, son, imza = ham.rsplit("|", 2)
    except Exception:
        return None
    d = durum()
    beklenen = hmac.new(d.secret.encode(), f"{kullanici}|{son}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(imza, beklenen):
        return None
    try:
        if int(son) < time.time():
            return None
    except ValueError:
        return None
    return kullanici


def giris_denenebilir(ip: str) -> bool:
    simdi = time.time()
    with _lock:
        gecmis = [t for t in _denemeler.get(ip, []) if simdi - t < PENCERE_SN]
        _denemeler[ip] = gecmis
        return len(gecmis) < AZAMI_DENEME


def giris_denemesi_kaydet(ip: str) -> None:
    with _lock:
        _denemeler.setdefault(ip, []).append(time.time())


def giris_sifirla(ip: str) -> None:
    with _lock:
        _denemeler.pop(ip, None)


# --------------------------------------------------------------------------- #
def require_user(request: Request,
                 feneri_oturum: str | None = Cookie(default=None)) -> str:
    """Korumali uc noktalarda bagimlilik olarak kullanilir."""
    if not settings.auth_enabled:
        return "anonim"
    kullanici = oturum_coz(feneri_oturum) if feneri_oturum else None
    if not kullanici:
        raise HTTPException(401, "Oturum açmanız gerekiyor")
    request.state.kullanici = kullanici
    return kullanici


Kullanici = Depends(require_user)
