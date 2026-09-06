"""Eşleştirme ve fark çıkarma testleri.

Ana iddia: her eski ve her yeni birim çıktıda TAM OLARAK BİR kez görünür.
Eşleştirme kalitesi ne olursa olsun hiçbir şey kaybolmaz.
"""
from __future__ import annotations

import pytest

from app.pipeline.compare import (
    SIM_THRESHOLD, align, similarity, stats, word_diff,
)
from app.pipeline.coverage import units_of


def _hizala(eski: str, yeni: str):
    return align(units_of(eski), units_of(yeni))


def _madde(no: int, baslik: str, govde: str) -> str:
    return f"MADDE {no} - {baslik}\n{govde}\n"


# --------------------------------------------------------------------------- #
# Bütünlük: hiçbir birim kaybolmaz
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("eski,yeni", [
    # değişiklik yok
    (_madde(1, "A", "Birinci madde gövdesi burada.") + _madde(2, "B", "İkinci madde gövdesi."),
     _madde(1, "A", "Birinci madde gövdesi burada.") + _madde(2, "B", "İkinci madde gövdesi.")),
    # madde eklendi
    (_madde(1, "A", "Birinci madde gövdesi burada.") + _madde(2, "B", "İkinci madde gövdesi."),
     _madde(1, "A", "Birinci madde gövdesi burada.") + _madde(2, "B", "İkinci madde gövdesi.")
     + _madde(3, "C", "Üçüncü madde eklendi.")),
    # madde silindi
    (_madde(1, "A", "Birinci madde gövdesi burada.") + _madde(2, "B", "İkinci madde gövdesi.")
     + _madde(3, "C", "Üçüncü madde gövdesi."),
     _madde(1, "A", "Birinci madde gövdesi burada.") + _madde(3, "C", "Üçüncü madde gövdesi.")),
    # tamamen farklı belgeler
    (_madde(1, "A", "Bambaşka bir metin burada duruyor."),
     _madde(9, "Z", "Hiç alakası olmayan başka bir metin.")),
])
def test_her_birim_tam_bir_kez_gorunur(eski, yeni):
    eski_u, yeni_u = units_of(eski), units_of(yeni)
    ch = align(eski_u, yeni_u)

    gorulen_eski = [c.old.order_index for c in ch if c.old is not None]
    gorulen_yeni = [c.new.order_index for c in ch if c.new is not None]

    assert sorted(gorulen_eski) == list(range(len(eski_u))), "eski birim kayıp veya mükerrer"
    assert sorted(gorulen_yeni) == list(range(len(yeni_u))), "yeni birim kayıp veya mükerrer"


# --------------------------------------------------------------------------- #
# Değişiklik türleri
# --------------------------------------------------------------------------- #
def test_degisen_madde_yakalanir():
    ch = _hizala(_madde(2, "BEDEL", "Aylık bedel 250.000 TL olarak ödenir."),
                 _madde(2, "BEDEL", "Aylık bedel 300.000 TL olarak ödenir."))
    d = [c for c in ch if c.change_type == "DEGISTI"]
    assert len(d) == 1
    eklenen = "".join(p["text"] for p in d[0].word_diff if p["op"] == "insert")
    silinen = "".join(p["text"] for p in d[0].word_diff if p["op"] == "delete")
    assert "300.000" in eklenen and "250.000" in silinen


def test_ayni_madde_ayni_isaretlenir():
    m = _madde(1, "A", "Hiç değişmeyen bir madde gövdesi burada.")
    ch = _hizala(m, m)
    assert [c.change_type for c in ch] == ["AYNI"]
    assert not ch[0].significant


def test_yalniz_bosluk_farki_onemsiz_sayilir():
    ch = _hizala(_madde(1, "A", "Boşluk  farkı   olan  madde."),
                 _madde(1, "A", "Boşluk farkı olan madde."))
    assert all(not c.significant for c in ch), "boşluk farkı modele gönderilmemeli"


def test_iri_blok_icinde_tek_kelime_degisikligi_yakalanir():
    """normalize() alt maddeleri tek bloğa toplayabiliyor (ölçüldü: 12.1-12.4).

    Blok iri olsa da içindeki tek kelimelik değişiklik işaretlenmeli.
    """
    govde = ("12.1 Tedarikçi taahhüt etmez. 12.2 Dolaylı zararlardan sorumlu değildir. "
             "12.3 Toplam sorumluluğu üç ayda ödenen bedeli aşamaz. "
             "12.4 Banka tazmin edecektir.")
    ch = _hizala(_madde(12, "SORUMLULUK", govde),
                 _madde(12, "SORUMLULUK", govde.replace("üç ayda", "on iki ayda")))
    d = [c for c in ch if c.change_type == "DEGISTI"]
    assert len(d) == 1 and d[0].significant
    eklenen = "".join(p["text"] for p in d[0].word_diff if p["op"] == "insert")
    assert "on iki" in eklenen


# --------------------------------------------------------------------------- #
# Bilinçli yanlılık: şüphede kalırsan eşleştirme
# --------------------------------------------------------------------------- #
def test_alakasiz_maddeler_ayni_numarayi_tasisa_bile_eslesmez():
    """Araya madde girip numaralar kaydığında yanlış eşleşme olmamalı.

    Yanlış eşleştirme, eşleştirmemekten tehlikeli: alakasız iki madde yan yana
    konur ve okuyan kişi anlamsız kartı atlar.
    """
    ch = _hizala(_madde(3, "GİZLİLİK", "Taraflar birbirlerinin sırlarını saklar."),
                 _madde(3, "FESİH", "Sözleşme otuz gün önceden bildirimle feshedilir."))
    turler = {c.change_type for c in ch}
    assert turler == {"SILINDI", "EKLENDI"}, f"alakasız maddeler eşleşti: {turler}"


def test_esik_altindaki_cift_silindi_eklendi_olur():
    a = _madde(1, "A", "Tamamen farklı bir metin buraya yazılmıştır efendim.")
    b = _madde(1, "A", "Bambaşka kelimelerden oluşan ikinci içerik bloğu.")
    assert similarity(a, b) < SIM_THRESHOLD, "test verisi eşiğin altında değil"
    ch = _hizala(a, b)
    assert {c.change_type for c in ch} == {"SILINDI", "EKLENDI"}


def test_yeniden_numaralanan_madde_tasindi_sayilir():
    """Gövdesi aynı kalıp numarası değişen madde 'taşındı' sayılır.

    Belgede en az üç başlık olmalı; altında segment() yedek paragraf moduna
    düşer ve numaraları kendisi yeniden atar.
    """
    gizli = "Taraflar arasındaki gizlilik yükümlülüğü beş yıl süreyle devam eder."
    sabit = (_madde(1, "TANIMLAR", "Terimler bu maddede tanımlanmıştır.")
             + _madde(2, "BEDEL", "Aylık bedel 250.000 TL olarak ödenir."))
    ch = _hizala(sabit + _madde(3, "GİZLİLİK", gizli),
                 sabit + _madde(4, "GİZLİLİK", gizli))
    tasinan = [c for c in ch if c.change_type == "TASINDI"]
    assert len(tasinan) == 1, [c.change_type for c in ch]
    assert tasinan[0].old.number == "3" and tasinan[0].new.number == "4"


# --------------------------------------------------------------------------- #
# Kapsama katmanıyla birlikte
# --------------------------------------------------------------------------- #
def test_preamble_degisikligi_gorunur():
    """Madde bazlı karşılaştırmanın atlayacağı yer: taraf adı değişikliği."""
    govde = _madde(1, "A", "Birinci madde gövdesi burada duruyor.") \
        + _madde(2, "B", "İkinci madde gövdesi burada.") \
        + _madde(3, "C", "Üçüncü madde gövdesi burada.")
    eski = "TEDARİK SÖZLEŞMESİ\nTaraflar: Banka A.Ş. ile Veriteknoloji Ltd. Şti.\n" + govde
    yeni = "TEDARİK SÖZLEŞMESİ\nTaraflar: Banka A.Ş. ile Veriteknoloji Bilişim A.Ş.\n" + govde

    ch = _hizala(eski, yeni)
    preamble = [c for c in ch if c.is_gap_unit and c.change_type != "AYNI"]
    assert preamble, "taraf değişikliği hiç görünmedi"
    eklenen = "".join(p["text"] for c in preamble for p in c.word_diff if p["op"] == "insert")
    assert "Bilişim" in eklenen


def test_stats_toplami_tutarli():
    ch = _hizala(_madde(1, "A", "Birinci madde gövdesi burada duruyor.")
                 + _madde(2, "B", "İkinci madde gövdesi burada."),
                 _madde(1, "A", "Birinci madde gövdesi değişti artık.")
                 + _madde(3, "C", "Yepyeni bir madde eklendi buraya."))
    s = stats(ch)
    assert s["toplam"] == len(ch)
    assert sum(s[t] for t in ("EKLENDI", "SILINDI", "DEGISTI", "TASINDI", "AYNI")) == s["toplam"]


def test_word_diff_metni_yeniden_uretir():
    """Fark segmentleri birleştirildiğinde iki metin de geri gelmeli."""
    a, b = "Aylık bedel 250.000 TL olarak ödenir.", "Aylık bedel 300.000 TL peşin ödenir."
    d = word_diff(a, b)
    assert "".join(p["text"] for p in d if p["op"] in ("equal", "delete")) == a
    assert "".join(p["text"] for p in d if p["op"] in ("equal", "insert")) == b
