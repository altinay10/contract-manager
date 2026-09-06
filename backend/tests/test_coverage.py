"""Kapsama katmanı testleri.

Buradaki asıl iddia şu: karşılaştırma metnin hiçbir yerini atlamaz. Bu bir
niyet beyanı değil, ölçülebilir bir koşul — birimlerin karakter aralıkları
birleştiğinde metnin tamamını vermek zorunda.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.coverage import build_units, units_of, verify_coverage
from app.pipeline.extract import extract_ex
from app.pipeline.normalize import normalize
from app.pipeline.segment import segment

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "ornek-saas-sozlesmesi.pdf"


def _kapsam(text: str, units) -> int:
    """Kaç karakter herhangi bir birime ait?"""
    isaretli = bytearray(len(text))
    for u in units:
        for i in range(u.char_start, min(u.char_end, len(text))):
            isaretli[i] = 1
    return sum(isaretli)


# --------------------------------------------------------------------------- #
# Temel koşul: %100 kapsam
# --------------------------------------------------------------------------- #
def test_ornek_sozlesme_tamamen_kapsanir():
    text = normalize(extract_ex(SAMPLE).text)
    units = units_of(text)
    assert _kapsam(text, units) == len(text), "örnek sözleşmede kapsanmayan karakter var"


def test_preamble_kendi_birimi_olur():
    """Ölçüm: örnek sözleşmenin ilk 224 karakteri hiçbir maddeye ait değildi.

    Sözleşmenin adı, tarafları ve tarihi orada. Madde bazlı karşılaştırma
    tedarikçi tüzel kişiliği değişse bunu göstermezdi.
    """
    text = normalize(extract_ex(SAMPLE).text)
    ilk_madde_basi = segment(text)[0].char_start
    assert ilk_madde_basi > 0, "bu belgede preamble yok, test anlamsız"

    units = units_of(text)
    assert units[0].is_gap, "preamble birime dönüşmemiş"
    assert units[0].char_start == 0
    assert "Örnek Katılım Bankası" in units[0].text
    assert "15.03.2026" in units[0].text


def test_yedek_modda_kisa_paragraf_kaybolmaz():
    """segment() yedek modda 80 karakterden kısa blokları atıyor.

    Ölçüm: "Bedel: 250.000 TL." (18 karakter) tamamen yok oluyordu. Bedel,
    tarih ve süre gibi kısa satırlar tam da bu boyutta.
    """
    metin = (
        "Bu bir sözleşme metnidir ve içinde madde başlığı bulunmamaktadır. " * 3
        + "\n\nBedel: 250.000 TL.\n\n"
        + "Taraflar arasındaki ilişki aşağıdaki şekilde düzenlenmiştir. " * 3
    )
    # Önce sorunu göster: ham segment() bedeli kaybediyor.
    assert not any("250.000" in c.text for c in segment(metin)), \
        "segment() artık bedeli kaybetmiyor — bu test güncellenmeli"

    # Kapsama katmanı onu geri getiriyor.
    units = units_of(metin)
    assert any("250.000" in u.text for u in units), "bedel hâlâ kayıp"
    assert _kapsam(metin, units) == len(metin)


def test_cok_paragrafli_madde_tek_birimde_kalir():
    """Normal modda birimler uç uca eklenir; aradaki paragraflar kaybolmaz."""
    metin = (
        "MADDE 1 - TANIMLAR\nBu sözleşmede geçen terimler aşağıdaki anlamları taşır.\n\n"
        "İkinci paragraf: Hizmet, Tedarikçi tarafından sağlanan yazılımı ifade eder.\n\n"
        "MADDE 2 - BEDEL\nAylık bedel 250.000 TL'dir.\n\n"
        "Ödeme her ayın beşinci günü yapılır.\n\n"
        "MADDE 3 - SÜRE\nSözleşme bir yıl süreyle geçerlidir.\n"
    )
    units = units_of(metin)
    assert _kapsam(metin, units) == len(metin)
    bedel = [u for u in units if "250.000" in u.text]
    assert len(bedel) == 1, "bedel birden fazla birime dağılmış"
    assert "beşinci günü" in bedel[0].text, "maddenin ikinci paragrafı ayrı düşmüş"


@pytest.mark.parametrize("metin", [
    "",
    "   \n\n  \n",
    "Tek satır.",
    "MADDE 1\nA\nMADDE 2\nB\nMADDE 3\nC\n",
    "\n\n\nMADDE 1 - A\nGövde metni burada.\nMADDE 2 - B\nİkinci gövde.\nMADDE 3 - C\nÜçüncü.\n",
    "Önsöz metni.\n\nMADDE 1 - A\nGövde.\nMADDE 2 - B\nGövde.\nMADDE 3 - C\nGövde.\n\nİmza: Banka",
])
def test_kenar_durumlarinda_kapsam_tam(metin):
    units = units_of(metin)          # verify_coverage içeride hata fırlatır
    assert _kapsam(metin, units) == len(metin)


def test_bosluk_tespit_edilirse_hata_verir():
    """verify_coverage sessizce geçmemeli — eksik kapsam karşılaştırmayı durdurur."""
    metin = "A" * 100
    units = build_units(metin)
    units[0].char_end = 50            # yapay boşluk aç
    with pytest.raises(ValueError, match="Kapsama boşluğu"):
        verify_coverage(metin, units)


def test_birimler_sirali_ve_bitisik():
    text = normalize(extract_ex(SAMPLE).text)
    units = units_of(text)
    for onceki, sonraki in zip(units, units[1:]):
        assert onceki.char_end == sonraki.char_start, "birimler arasında boşluk/çakışma"
    assert units[0].char_start == 0
    assert units[-1].char_end == len(text)
