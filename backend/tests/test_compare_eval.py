"""Doğruluk ölçümü — gerçekçi revizyon senaryoları üzerinde.

Buradaki ölçüm modelin iyiliğini değil, **mimarinin garantisini** sınar:
karşılaştırmayı deterministik katman yaptığı için değişiklik recall'ı modelden
bağımsızdır. Senaryolar bir banka tedarik sözleşmesinde gerçekten karşılaşılan
revizyon türlerinden seçilmiştir.

Taraf etkisi isabeti gerçek bir model gerektirir; bu dosya onun koşum
düzeneğini kurar, iddiada bulunmaz.
"""
from __future__ import annotations

import pytest

from app.pipeline.compare import align, stats
from app.pipeline.compare_explain import verify_anchors
from app.pipeline.coverage import units_of

BASLIK = ("YAZILIM HİZMETİ TEDARİK SÖZLEŞMESİ\n"
          "İşbu Sözleşme, Örnek Katılım Bankası A.Ş. ile {tedarikci} arasında "
          "15.03.2026 tarihinde akdedilmiştir.\n")


def _govde(**degisiklikler) -> str:
    maddeler = {
        "sorumluluk": "Tedarikçi'nin toplam sorumluluğu, son üç ayda ödenen bedeli aşamaz.",
        "odeme": "Ödemeler fatura tarihinden itibaren 30 gün içinde yapılır.",
        "fesih": "Taraflar 60 gün önceden yazılı bildirimle sözleşmeyi feshedebilir.",
        "gizlilik": "Gizlilik yükümlülüğü sözleşmenin sona ermesinden itibaren 5 yıl sürer.",
        "denetim": "Banka, Tedarikçi'nin tesislerinde yılda bir kez denetim yapabilir.",
    }
    maddeler.update(degisiklikler)
    sira = ["sorumluluk", "odeme", "fesih", "gizlilik", "denetim"]
    basliklar = {"sorumluluk": "SORUMLULUK", "odeme": "ÖDEME", "fesih": "FESİH",
                 "gizlilik": "GİZLİLİK", "denetim": "DENETİM"}
    out = []
    for i, k in enumerate(sira, start=1):
        if maddeler.get(k) is None:
            continue
        out.append(f"MADDE {i} - {basliklar[k]}\n{maddeler[k]}\n")
    return "".join(out)


def _belge(tedarikci="Veriteknoloji Bilişim Ltd. Şti.", **kw) -> str:
    return BASLIK.format(tedarikci=tedarikci) + _govde(**kw)


# (ad, yeni belge, çıktıda mutlaka görünmesi gereken metin parçası)
SENARYOLAR = [
    ("sorumluluk tavanı gevşetildi",
     _belge(sorumluluk="Tedarikçi'nin toplam sorumluluğu, son 1 ayda ödenen bedeli aşamaz."),
     "1 ayda"),
    ("ödeme süresi uzatıldı",
     _belge(odeme="Ödemeler fatura tarihinden itibaren 90 gün içinde yapılır."),
     "90 gün"),
    ("fesih hakkı tek taraflılaştırıldı",
     _belge(fesih="Yalnızca Tedarikçi 15 gün önceden bildirimle sözleşmeyi feshedebilir."),
     "Yalnızca Tedarikçi"),
    ("gizlilik süresi kısaltıldı",
     _belge(gizlilik="Gizlilik yükümlülüğü sözleşmenin sona ermesinden itibaren 1 yıl sürer."),
     "1 yıl"),
    ("denetim maddesi tamamen silindi",
     _belge(denetim=None),
     "denetim yapabilir"),
    ("tedarikçi tüzel kişiliği değişti",
     _belge(tedarikci="Veriteknoloji Bilişim Anonim Şirketi"),
     "Anonim Şirketi"),
]


def _eski() -> str:
    return _belge()


@pytest.mark.parametrize("ad,yeni,beklenen", SENARYOLAR,
                         ids=[s[0] for s in SENARYOLAR])
def test_degisiklik_recall_yuzde_yuz(ad, yeni, beklenen):
    """Her senaryodaki değişiklik çıktıda GÖRÜNMEK ZORUNDA.

    Bu testin modelden hiç haberi yok — recall'ı deterministik katman
    garantiliyor. LLM'i yorumcuya indirgemenin asıl kazancı budur.
    """
    ch = align(units_of(_eski()), units_of(yeni))
    gorunur = " ".join(
        (c.old.text if c.old else "") + " " + (c.new.text if c.new else "")
        for c in ch if c.change_type != "AYNI"
    )
    assert beklenen in gorunur, f"{ad}: '{beklenen}' hiçbir değişiklik kartında görünmüyor"


@pytest.mark.parametrize("ad,yeni,_b", SENARYOLAR, ids=[s[0] for s in SENARYOLAR])
def test_her_senaryoda_kapsama_tam(ad, yeni, _b):
    eu, nu = units_of(_eski()), units_of(yeni)
    ch = align(eu, nu)
    assert sorted(c.old.order_index for c in ch if c.old) == list(range(len(eu)))
    assert sorted(c.new.order_index for c in ch if c.new) == list(range(len(nu)))


@pytest.mark.parametrize("ad,yeni,_b", SENARYOLAR, ids=[s[0] for s in SENARYOLAR])
def test_degisiklik_gurultusu_makul(ad, yeni, _b):
    """Tek maddelik revizyon, tüm sözleşmeyi 'değişti' göstermemeli."""
    ch = align(units_of(_eski()), units_of(yeni))
    s = stats(ch)
    assert s["AYNI"] >= 3, f"{ad}: değişmeyen madde sayısı beklenenden az ({s})"


def test_halusinasyon_orani_olculebilir():
    """Çapa doğrulaması uydurma sayıyı yakalıyor, gerçeğini geçiriyor.

    Halüsinasyon oranı = bu kapıdan geçemeyen açıklama oranı; koşucu bunu
    stats_json'a yazacak.
    """
    eski_m = "Ödemeler fatura tarihinden itibaren 30 gün içinde yapılır."
    yeni_m = "Ödemeler fatura tarihinden itibaren 90 gün içinde yapılır."

    dogru, _ = verify_anchors("Ödeme süresi 30 günden 90 güne çıkarıldı.", "", eski_m, yeni_m)
    uydurma, not_ = verify_anchors("Ödeme süresi 30 günden 120 güne çıkarıldı.", "", eski_m, yeni_m)

    assert dogru, "gerçek sayı içeren açıklama reddedildi"
    assert not uydurma and "120" in not_, "uydurma sayı yakalanmadı"


def test_taraf_degisikligi_preamble_kapsamasi_sayesinde_gorunur():
    """Madde bazlı bir karşılaştırmanın atlayacağı senaryo."""
    ch = align(units_of(_eski()),
               units_of(_belge(tedarikci="Veriteknoloji Bilişim Anonim Şirketi")))
    preamble = [c for c in ch if c.is_gap_unit and c.change_type != "AYNI"]
    assert len(preamble) == 1
    eklenen = "".join(p["text"] for p in preamble[0].word_diff if p["op"] == "insert")
    assert "Anonim" in eklenen
