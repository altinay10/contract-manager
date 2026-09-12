"""IP basina istek freni.

Neden burada: uygulama herkese aciktir, yani yukleme ucu de aciktir. Acik aga
konulan bir Raspberry Pi'de bu, diski doldurma ve islemciyi kilitleme yoludur —
40 MB'lik bir PDF'in 300 dpi OCR'i ucuz degildir.

Ek bagimlilik yok: `auth.giris_denenebilir` ile ayni desen (surgulu pencere,
bellekte sozluk). Tek surec / tek konteyner kurulumu icindir; birden fazla
kopya kosulursa fren kopya basina isler. O noktada is ters vekile devredilir.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_gecmis: dict[str, list[float]] = {}

# Sozluk anahtar basina buyur; anahtar IP'dir. Farkli IP'lerden gelen bir sel,
# frenin kendisini bellek sizintisina cevirebilir — engelledigi seyin aynisi.
# Bu tavan asilinca suresi gecmis kayitlar suprulur.
AZAMI_ANAHTAR = 5000


def _suzgec(simdi: float, pencere_sn: int) -> None:
    """Suresi gecmis anahtarlari duser. Cagirani kilidi tutmus olmali."""
    olu = [a for a, t in _gecmis.items() if not t or simdi - max(t) >= pencere_sn]
    for a in olu:
        _gecmis.pop(a, None)


def izin_var(anahtar: str, azami: int, pencere_sn: int = 3600) -> bool:
    """Kotayi tuketmeden sorar ve tuketir. azami <= 0 ise sinir yoktur."""
    if azami <= 0:
        return True
    simdi = time.time()
    with _lock:
        if len(_gecmis) > AZAMI_ANAHTAR:
            _suzgec(simdi, pencere_sn)
        gecmis = [t for t in _gecmis.get(anahtar, []) if simdi - t < pencere_sn]
        if len(gecmis) >= azami:
            _gecmis[anahtar] = gecmis
            return False
        gecmis.append(simdi)
        _gecmis[anahtar] = gecmis
        return True


def kalan(anahtar: str, azami: int, pencere_sn: int = 3600) -> int:
    if azami <= 0:
        return -1
    simdi = time.time()
    with _lock:
        gecmis = [t for t in _gecmis.get(anahtar, []) if simdi - t < pencere_sn]
        return max(0, azami - len(gecmis))


def sifirla(anahtar: str | None = None) -> None:
    """Testler ve elle mudahale icin."""
    with _lock:
        if anahtar is None:
            _gecmis.clear()
        else:
            _gecmis.pop(anahtar, None)
