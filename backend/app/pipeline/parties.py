"""Taraf coczumleyici — sozlesmedeki ALICI tarafi kim?

Kural desenleri "banka" kelimesine sabitlenmisti. Gercek sozlesmelerde alici
tarafin tanimli adi "Banka" olmayabilir ("PRATIK ISLEM", "IDARE", "IS SAHIBI"...).
Bu durumda 11 kirmizi cizgi desenı SESSIZCE kaciyordu.

Cozum: sozlesmenin taraflar maddesinden tirnak icindeki tanimli terimleri cikar,
tedarikci tarafini eleyerek aliciyi bul ve desenlerdeki {ALICI} yer tutucusunu
bu adlarla doldur.
"""
from __future__ import annotations

import re

from ..textutil import fold

# Tirnak icindeki tanimli terimler: ("Banka"), (“PRATİK İŞLEM”) ...
_TANIM = re.compile(r"[(\[]\s*[\"“”'‘’]\s*([^\"“”'‘’\n\]\)]{2,45}?)\s*[\"“”'‘’]\s*[)\]]")

# Taraf adi olmayan, her sozlesmede gecen genel tanimlar.
_GENEL = {
    "sözleşme", "taraf", "taraflar", "ek", "ekler", "hizmet", "hizmetler",
    "gizli bilgi", "gizli bilgiler", "ürün", "yazılım", "sistem", "kanun",
    "yönetmelik", "kurum", "kurul", "veri", "personel",
}

# Tedarikci tarafini isaret eden kelimeler.
_TEDARIKCI_IZI = (
    "tedarikçi", "sağlayıcı", "yüklenici", "satıcı", "firma", "şirket",
    "hizmet sağlayıcı", "danışman", "imalatçı", "üretici", "kiralayan",
)

# Alici tarafi isaret eden, sozlesmede tanim bulunamazsa kullanilan genel adlar.
VARSAYILAN_ALICI = ("banka", "müşteri", "alıcı", "iş sahibi", "idare", "kurum")


def tanimli_terimler(text: str, limit: int = 6000) -> list[str]:
    bas = text[:limit]
    out: list[str] = []
    for m in _TANIM.finditer(bas):
        ad = re.sub(r"\s+", " ", m.group(1)).strip()
        if not ad or fold(ad) in _GENEL:
            continue
        if ad not in out:
            out.append(ad)
    return out


def taraflari_ayir(text: str) -> tuple[list[str], list[str]]:
    """(alici_adlari, tedarikci_adlari)"""
    alici, tedarikci = [], []
    for ad in tanimli_terimler(text):
        f = fold(ad)
        if any(iz in f for iz in _TEDARIKCI_IZI):
            tedarikci.append(ad)
        else:
            alici.append(ad)
    return alici, tedarikci


def alici_deseni(text: str) -> str:
    """{ALICI} yer tutucusunun yerine gececek regex parcasi."""
    alici, _ = taraflari_ayir(text)
    adlar = [fold(a) for a in alici] + list(VARSAYILAN_ALICI)
    # Uzun olan once: "iş sahibi" | "iş" siralamasi onemli
    adlar = sorted({a for a in adlar if a}, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(a) for a in adlar) + ")"
