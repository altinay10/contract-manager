"""Açıklama katmanı testleri.

Ana iddia: model karşılaştırmayı YAPMAZ, YORUMLAR. Dolayısıyla model ne yaparsa
yapsın — hata verir, atlar, uydurur — hiçbir değişiklik ekrandan kaybolmaz.
"""
from __future__ import annotations

import pytest

from app.llm.budget import Budget, BudgetExceeded
from app.llm.provider import Completion, LLMError, Turn, Usage
from app.pipeline.compare import align, GRAY_LOW, SIM_THRESHOLD, similarity
from app.pipeline.compare_explain import (
    build_explain_task, explain_change, make_adjudicator, rebut_change,
    template_explanation, triage, verify_anchors,
)
from app.pipeline.coverage import units_of


# --------------------------------------------------------------- sahte model
class SahteSaglayici:
    """Şema uyumlu sahte model. `mod` ile kötü davranış senaryoları kurulur."""

    name = "sahte"
    is_llm = True

    def __init__(self, mod: str = "normal", hakem_karari: str = "FARKLI_MADDE"):
        self.mod = mod
        self.hakem_karari = hakem_karari
        self.cagri = 0
        self.gorulen_promptlar: list[str] = []
        self.gorulen_ajanlar: list[str] = []

    def complete_json(self, turn: Turn, budget: Budget | None = None) -> Completion:
        if budget is not None:
            budget.check()
        self.cagri += 1
        self.gorulen_promptlar.append(turn.task_block)
        self.gorulen_ajanlar.append(turn.agent)

        if self.mod == "hep_hata":
            raise LLMError("simüle edilmiş geçici hata")

        data = self._cevap(turn)
        return Completion(data=data, usage=Usage(model="sahte", input_tokens=100,
                                                 output_tokens=50, cost_usd=0.001))

    def _cevap(self, turn: Turn) -> dict:
        if turn.agent == "RevizyonHakemi":
            return {"verdict": self.hakem_karari, "gerekce": "test"}
        if turn.agent == "RevizyonTriyaji":
            if self.mod == "triyaj_atlar":
                return {"results": []}          # model hiçbir kalemi döndürmüyor
            ids = [s.split("id=")[1].split(" ")[0]
                   for s in turn.task_block.split("\n") if "id=" in s]
            return {"results": [{"id": i, "materiality": "ESASLI"} for i in ids]}
        if turn.agent == "RevizyonKarsiGorus":
            return {"verdict": "GECERSIZ", "rebuttal": "dengeleyen başka madde var"}
        # RevizyonAnalisti
        if self.mod == "uydurma":
            return {"explanation": "Süre 30 günden 999 güne çıkarıldı.",
                    "impact": "TEDARIKCI_LEHINE", "impact_note": "",
                    "quote": "", "injection_attempt": False}
        return {"explanation": "Ödeme süresi uzatıldı.",
                "impact": "TEDARIKCI_LEHINE",
                "impact_note": "Alıcı parasını daha geç alır.",
                "quote": "", "injection_attempt": False}


class SahteHeuristic:
    name = "heuristic"
    is_llm = False

    def complete_json(self, turn, budget=None):
        raise AssertionError("model olmadan çağrı yapılmamalı")


def _madde(no: int, baslik: str, govde: str) -> str:
    return f"MADDE {no} - {baslik}\n{govde}\n"


SABIT = (_madde(1, "TANIMLAR", "Terimler bu maddede tanımlanmıştır.")
         + _madde(2, "TARAFLAR", "Taraflar aşağıda belirtilmiştir."))


# --------------------------------------------------------------------------- #
# Hakem — kapsama garantisi model ne derse desin bozulmaz
# --------------------------------------------------------------------------- #
def _gri_bant_ciftleri():
    """Benzerliği gri bantta kalan bir eski/yeni sürüm çifti üretir."""
    # Madde numarası da değişmeli: aynı numara taşısalardı numara eşleşmesi
    # devreye girer ve çift gri banta hiç ulaşmaz.
    eski = SABIT + _madde(3, "ÖDEME",
                          "Ödemeler fatura tarihinden itibaren otuz gün içinde yapılır.")
    yeni = SABIT + _madde(9, "ÖDEME",
                          "Ödemeler, faturanın tebliğinden itibaren altmış gün içinde "
                          "banka havalesiyle yapılır.")
    eu, nu = units_of(eski), units_of(yeni)
    return eski, yeni, eu, nu


def test_gri_bant_gercekten_gri_banttadir():
    """Test verisi kurgusunun geçerliliği: eşik altında ama yok saymayacak kadar benzer."""
    _, _, eu, nu = _gri_bant_ciftleri()
    s = similarity(eu[-1].text, nu[-1].text)
    assert GRAY_LOW <= s < SIM_THRESHOLD, f"benzerlik {s:.2f} gri bantta değil"


def test_hakem_farkli_madde_derse_iki_kart_kalir():
    _, _, eu, nu = _gri_bant_ciftleri()
    saglayici = SahteSaglayici(hakem_karari="FARKLI_MADDE")
    ch = align(eu, nu, adjudicator=make_adjudicator(saglayici))
    turler = [c.change_type for c in ch if c.change_type != "AYNI"]
    assert sorted(turler) == ["EKLENDI", "SILINDI"]


def test_hakem_ayni_madde_derse_tek_karta_iner():
    _, _, eu, nu = _gri_bant_ciftleri()
    saglayici = SahteSaglayici(hakem_karari="AYNI_MADDE")
    ch = align(eu, nu, adjudicator=make_adjudicator(saglayici))
    birlesen = [c for c in ch if c.change_type == "DEGISTI" and c.adjudicated]
    assert len(birlesen) == 1, [c.change_type for c in ch]


@pytest.mark.parametrize("karar", ["AYNI_MADDE", "FARKLI_MADDE"])
def test_hakem_ne_derse_desin_hicbir_birim_kaybolmaz(karar):
    """Kapsama garantisi modelin kararından bağımsızdır."""
    _, _, eu, nu = _gri_bant_ciftleri()
    ch = align(eu, nu, adjudicator=make_adjudicator(SahteSaglayici(hakem_karari=karar)))
    assert sorted(c.old.order_index for c in ch if c.old) == list(range(len(eu)))
    assert sorted(c.new.order_index for c in ch if c.new) == list(range(len(nu)))


def test_hakem_cokerse_eslestirme_yapilmaz():
    """Güvenli yön: hakem hata verirse eşleştirmiyoruz, iki kart kalıyor."""
    _, _, eu, nu = _gri_bant_ciftleri()
    ch = align(eu, nu, adjudicator=make_adjudicator(SahteSaglayici(mod="hep_hata")))
    assert not any(c.adjudicated for c in ch)
    assert sorted(c.old.order_index for c in ch if c.old) == list(range(len(eu)))


def test_model_yoksa_hakem_uretilmez():
    assert make_adjudicator(SahteHeuristic()) is None


# --------------------------------------------------------------------------- #
# Çapa doğrulaması
# --------------------------------------------------------------------------- #
def test_uydurma_sayi_yakalanir():
    ok, not_ = verify_anchors("Süre 30 günden 999 güne çıkarıldı.", "",
                              "otuz gün 30 gün içinde", "altmış gün 60 gün içinde")
    assert not ok and "999" in not_


def test_metinde_gecen_sayi_dogrulanir():
    ok, not_ = verify_anchors("Süre 30 günden 60 güne çıkarıldı.", "",
                              "ödeme 30 gün içinde", "ödeme 60 gün içinde")
    assert ok, not_


def test_bulunamayan_alinti_yakalanir():
    ok, not_ = verify_anchors("Bir açıklama.", "sözleşmede hiç geçmeyen bir cümle",
                              "eski metin burada", "yeni metin burada")
    assert not ok and "Alıntı" in not_


def test_kisa_alinti_dogrulamayi_dusurmez():
    """find_quote 12 karakterden kısa alıntıyı zaten reddediyor; ceza yazmayalım."""
    ok, _ = verify_anchors("Bir açıklama.", "kısa", "eski metin", "yeni metin")
    assert ok


# --------------------------------------------------------------------------- #
# Triyaj — döngü deterministik listede döner
# --------------------------------------------------------------------------- #
def _degisiklikler():
    eski = SABIT + _madde(3, "BEDEL", "Aylık bedel 250.000 TL olarak ödenir.")
    yeni = SABIT + _madde(3, "BEDEL", "Aylık bedel 300.000 TL olarak ödenir.")
    return align(units_of(eski), units_of(yeni))


def test_triyaj_modelin_atladigi_kalem_kaybolmaz():
    """gaps.py deseni: model boş liste dönse bile her değişikliğin ağırlığı olur."""
    ch = _degisiklikler()
    hedefler = [c for c in ch if c.change_type != "AYNI"]
    kararlar, _ = triage(SahteSaglayici(mod="triyaj_atlar"), ch)
    assert set(kararlar) == {c.order_index for c in hedefler}
    # Sayı içeren fark deterministik yedekte ESASLI sayılır.
    assert all(v == "ESASLI" for v in kararlar.values()), kararlar


def test_triyaj_model_yoksa_deterministik_calisir():
    ch = _degisiklikler()
    kararlar, comp = triage(SahteHeuristic(), ch)
    assert comp is None
    assert kararlar and all(v in ("ESASLI", "KUCUK", "BICIMSEL") for v in kararlar.values())


def test_triyaj_ucuz_model_ister():
    ch = _degisiklikler()
    saglayici = SahteSaglayici()
    triage(saglayici, ch)
    assert "RevizyonTriyaji" in saglayici.gorulen_ajanlar


# --------------------------------------------------------------------------- #
# Açıklama — K2: ne değiştiği modele VERİLİR
# --------------------------------------------------------------------------- #
def test_prompt_farkin_kendisini_iceriyor():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    task = build_explain_task(ch, alici="Örnek Bankası", tedarikci="Veriteknoloji")
    assert "TAM OLARAK NE DEGISTI" in task
    assert "250.000" in task and "300.000" in task
    assert "Örnek Bankası" in task and "Veriteknoloji" in task
    assert "DEGISIKLIK TURU (KESIN)" in task


def test_model_yoksa_sablon_aciklama_yazilir():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    sonuc, comp = explain_change(SahteHeuristic(), ch)
    assert comp is None
    assert sonuc["explained_by"] == "RULE"
    assert sonuc["impact"] == "BELIRSIZ"
    assert sonuc["explanation"]


def test_model_hatasinda_sablona_dusulur():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    sonuc, _ = explain_change(SahteSaglayici(mod="hep_hata"), ch)
    assert sonuc["explained_by"] == "RULE"
    assert sonuc["explanation"]


def test_butce_dolunca_sablona_dusulur_akis_cokmez():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    b = Budget()
    b._disable("test: tavan doldu")
    sonuc, comp = explain_change(SahteSaglayici(), ch, budget=b)
    assert comp is None
    assert sonuc["explained_by"] == "RULE"


def test_gecersiz_impact_belirsize_dusurulur():
    class BozukModel(SahteSaglayici):
        def _cevap(self, turn):
            return {"explanation": "bir şey", "impact": "SAÇMA_DEĞER",
                    "impact_note": "", "quote": "", "injection_attempt": False}

    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    sonuc, _ = explain_change(BozukModel(), ch)
    assert sonuc["impact"] == "BELIRSIZ"


def test_sablon_aciklama_uydurmaz():
    for c in _degisiklikler():
        metin = template_explanation(c)
        assert metin and "lehine" not in metin.lower()


# --------------------------------------------------------------------------- #
# K7 karşı-görüş
# --------------------------------------------------------------------------- #
def test_karsi_gorus_gecersiz_derse_etki_belirsize_doner():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    out, _ = rebut_change(SahteSaglayici(), ch, "Bedel arttı.", "Alıcı daha çok öder.")
    assert out["impact"] == "BELIRSIZ"
    assert out["rebuttal"]


def test_karsi_gorus_model_yoksa_sessizce_atlanir():
    ch = [c for c in _degisiklikler() if c.change_type == "DEGISTI"][0]
    out, comp = rebut_change(SahteHeuristic(), ch, "x", "y")
    assert out == {} and comp is None
