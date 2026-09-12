"""Istek freni — frenin kendisi bir kacak yolu olmamali."""
from __future__ import annotations

import time

from app import ratelimit


def test_sinir_tuketilir_ve_reddeder():
    ratelimit.sifirla()
    assert ratelimit.izin_var("a", 2) is True
    assert ratelimit.izin_var("a", 2) is True
    assert ratelimit.izin_var("a", 2) is False
    assert ratelimit.kalan("a", 2) == 0
    # Anahtarlar birbirinden bagimsiz.
    assert ratelimit.izin_var("b", 2) is True


def test_sifir_sinir_serbesttir():
    ratelimit.sifirla()
    for _ in range(50):
        assert ratelimit.izin_var("c", 0) is True
    assert ratelimit.kalan("c", 0) == -1


def test_pencere_gecince_kota_yenilenir():
    ratelimit.sifirla()
    assert ratelimit.izin_var("d", 1, pencere_sn=1) is True
    assert ratelimit.izin_var("d", 1, pencere_sn=1) is False
    time.sleep(1.05)
    assert ratelimit.izin_var("d", 1, pencere_sn=1) is True


def test_anahtar_sozlugu_sinirsiz_buyumez():
    """Farkli IP'lerden gelen sel, frenin kendisini bellek sizintisina cevirmemeli.

    Tavan asilinca suresi gecmis anahtarlar supruluyor mu?
    """
    ratelimit.sifirla()
    tavan = ratelimit.AZAMI_ANAHTAR
    for i in range(tavan + 50):
        ratelimit.izin_var(f"ip-{i}", 5, pencere_sn=0.2)
    time.sleep(0.25)                      # tum kayitlarin suresi gecti
    ratelimit.izin_var("tetikleyici", 5, pencere_sn=0.2)
    assert len(ratelimit._gecmis) < tavan, (
        f"suresi gecmis anahtarlar suprulmedi ({len(ratelimit._gecmis)} anahtar)"
    )
    ratelimit.sifirla()
