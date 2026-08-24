"""Cekirdek davranis testleri.

Odak: sessizce bozulabilecek seyler. Sozlesme metninde bir regex kacagi ya da
bir grounding zafiyeti, ekranda hata vermeden yanlis rapor uretir.
"""
from __future__ import annotations

import pytest

from app.playbook.loader import load_playbook, mandatory_codes
from app.pipeline.classify import classify
from app.pipeline.redlines import evaluate_red_lines, find_ambiguous
from app.pipeline.scoring import contract_score
from app.pipeline.segment import segment, _match_heading
from app.pipeline.normalize import normalize
from app.pipeline.meta import extract_meta
from app.textutil import find_quote, fold


# --------------------------------------------------------------- playbook
def test_playbook_yuklenir_ve_dogrulanir():
    pb = load_playbook()
    assert len(pb) >= 20
    for code, ct in pb.items():
        assert ct.name_tr, f"{code}: name_tr bos"
        assert 1 <= ct.weight <= 5
        if ct.obligation == "ZORUNLU":
            assert ct.ideal_text_tr, f"{code}: zorunlu maddenin ideal metni olmali"


def test_zorunlu_madde_kumesi_sozlesme_tipine_gore_degisir():
    saas = set(mandatory_codes("SAAS"))
    donanim = set(mandatory_codes("DONANIM"))
    assert saas != donanim
    assert "DATA_LOCATION" in saas
    assert "DATA_LOCATION" not in donanim


# --------------------------------------------------------------- metin
@pytest.mark.parametrize("line,beklenen", [
    ("MADDE 4 - SÜRE", True),
    ("12.3 Sorumluluğun Sınırlandırılması", True),
    ("7. GİZLİLİK", True),
    ("EK-2 FİYAT LİSTESİ", True),
    ("Article 9 Termination", True),
    ("01.01.2026 tarihinde imzalanmıştır", False),
    ("1.500,00 TL tutarındaki bedel", False),
    ("Bu normal bir cümledir ve başlık değildir.", False),
])
def test_baslik_tespiti(line, beklenen):
    assert (_match_heading(line) is not None) is beklenen


def test_madde_offsetleri_kaynak_metinle_ortusur():
    text = normalize(
        "SÖZLEŞME\n\nMADDE 1 - KONU\nBirinci madde metni burada.\n\n"
        "MADDE 2 - SÜRE\nİkinci madde metni burada.\n\nEK-1 LİSTE\nEk içeriği.\n"
    )
    for c in segment(text):
        assert text[c.char_start:c.char_end].strip() == c.text


def test_turkce_kucultme_regexi_bozmaz():
    # Python'un .lower() metodu 'İ' harfini bozar; kendi katlayicimiz bozmamali.
    assert fold("İHLAL BİLDİRİMİ") == "ihlal bildirimi"
    assert fold("IŞIK") == "ışık"


# --------------------------------------------------------------- grounding
def test_alinti_dogrulama_bosluk_ve_tirnak_toleransli():
    kaynak = "Tedarikçi'nin  işbu\nSözleşme'den doğan toplam sorumluluğu üç (3) ayı aşamaz."
    assert find_quote(kaynak, "işbu Sözleşme'den doğan toplam sorumluluğu") is not None
    assert find_quote(kaynak, "ÜÇ (3) AYI AŞAMAZ") is not None


def test_uydurma_alinti_reddedilir():
    kaynak = "Tedarikçi sorumluluğu sınırlıdır."
    assert find_quote(kaynak, "Bu cümle sözleşmede hiç geçmiyor ama model uydurdu") is None


# --------------------------------------------------------------- tespit
def test_sorumluluk_tavani_kirmizi_cizgisi_yakalanir():
    pb = load_playbook()
    metin = (
        "Tedarikçi'nin işbu Sözleşme'den doğan toplam sorumluluğu, talebin doğduğu "
        "tarihten önceki üç (3) ayda ödenen bedeli aşamaz."
    )
    ids = {h.red_line.id for h in evaluate_red_lines(metin, pb["LIMITATION_OF_LIABILITY"])}
    assert "LOL_LOW_CAP" in ids
    assert "LOL_NO_CARVEOUT" in ids


def test_uygun_madde_bulgu_uretmez():
    pb = load_playbook()
    iyi = pb["LIMITATION_OF_LIABILITY"].ideal_text_tr
    hits = evaluate_red_lines(iyi, pb["LIMITATION_OF_LIABILITY"])
    assert not [h for h in hits if h.red_line.id == "LOL_NO_CARVEOUT"]


def test_belirsiz_ifade_turkce_karakterli_ve_karaktersiz_yakalanir():
    assert find_ambiguous("Tedarikçi makul bir süre içinde bildirir.")
    assert find_ambiguous("Tedarikci makul bir sure icinde bildirir.")
    assert not find_ambiguous("Tedarikçi yirmi dört (24) saat içinde bildirir.")


def test_yokluk_kurali_kapsam_metnine_bakar():
    """Ayni madde tipine ait baska bir maddede koruma varsa eksik sayilmamali."""
    pb = load_playbook()
    madde = "Tedarikçi'nin sorumluluğu sınırlıdır."
    kapsam = madde + " Kasıt ve ağır kusur hâlleri bu sınırlamadan istisnadır."
    yalniz = {h.red_line.id for h in evaluate_red_lines(madde, pb["LIMITATION_OF_LIABILITY"])}
    kapsamli = {h.red_line.id for h in evaluate_red_lines(
        madde, pb["LIMITATION_OF_LIABILITY"], scope_text=kapsam)}
    assert "LOL_NO_CARVEOUT" in yalniz
    assert "LOL_NO_CARVEOUT" not in kapsamli


def test_siniflandirma_dogru_madde_tipini_bulur():
    kodlar = [c["code"] for c in classify(
        "İhlal Bildirimi",
        "Tedarikçi, güvenlik ihlalini öğrenmesini müteakip Banka'ya bildirimde bulunur.",
        "SAAS")]
    assert "BREACH_NOTIFICATION" in kodlar


# --------------------------------------------------------------- meta & skor
def test_meta_cikarimi_sozlesme_suresini_yenileme_suresiyle_karistirmaz():
    metin = (
        "Sözleşme süresi üç (3) yıldır. Sözleşme kendiliğinden bir yıl uzar."
    )
    assert extract_meta(metin)["term_text"] == "3 yıl"


def test_kirmizi_cizgi_veto_kurali_skoru_ezer():
    tek = [{"code": "LIMITATION_OF_LIABILITY", "severity": "KRITIK",
            "finding_type": "RED_LINE", "confidence": 0.9}]
    skor, band, veto = contract_score(tek, True, False)
    assert band == "KIRMIZI"
    assert veto
    assert skor > 60  # skor iyi olsa bile band kirmizi


def test_temiz_sozlesme_yesil_bant_alir():
    skor, band, veto = contract_score([], True, False)
    assert skor == 100.0 and band == "YESIL" and not veto


def test_tekrar_temizligi_gercek_cumleleri_silmez():
    """Ustbilgi elenmeli, ama tekrar eden gercek madde metni korunmali."""
    from app.pipeline.normalize import normalize

    cumle = "Taraflar işbu maddeye uymayı kabul ve taahhüt eder."
    ustbilgi = "Gizli - Örnek Bankası A.Ş."
    satirlar = []
    for i in range(30):
        satirlar += [ustbilgi, f"MADDE {i+1} - BAŞLIK", cumle, ""]
    metin = normalize("\n".join(satirlar))

    assert ustbilgi not in metin, "üstbilgi elenmedi"
    assert metin.count(cumle) == 30, "tekrar eden gerçek cümle silinmiş"


# --------------------------------------------------------------- Türkçe eşleştirme
# Bu testler gercek hatalardan dogdu: "telif" anahtari "MUHTELIF" icinde eslesiyordu
# ve "veri merkezi" anahtari "veri merkezlerinde" ifadesini kaciriyordu.

@pytest.mark.parametrize("anahtar,metin,beklenen", [
    # ek toleransi (kacirma hatasi)
    ("veri merkezi", "uygun göreceği veri merkezlerinde işlenebilir", True),
    ("denetim hakkı", "denetim hakkına sahiptir", True),
    ("garanti süresi", "garanti süresi boyunca", True),
    ("bakım bedeli", "yıllık bakım bedelleri", True),
    ("münhasır", "münhasıran kullanılır", True),
    # unsuz yumusamasi
    ("sorumluluk", "toplam sorumluluğu aşamaz", True),
    # cok kelimeli anahtarda her kelime ek alabilir
    ("hizmeti geliştirmek", "hizmetlerini geliştirmek amacıyla", True),
    # fiilden turemis isim
    ("kayıt saklama", "kayıtların saklanması", True),
    # kelime siniri (yanlis pozitif hatasi)
    ("telif", "MADDE 21 - MUHTELİF hükümler", False),
    ("fesih", "sözleşmeyi feshedebilir", False),
    ("ihlal bildirimi", "güvenlik ihlalini öğrenmesi", False),
])
def test_anahtar_kelime_esleşmesi_turkce_uyumlu(anahtar, metin, beklenen):
    from app.pipeline.classify import keyword_pattern
    from app.textutil import fold

    assert bool(keyword_pattern(anahtar).search(fold(metin))) is beklenen


@pytest.mark.parametrize("baslik,govde,beklenen_kod", [
    ("VERİLERİN İŞLENMESİ VE SAKLANMASI",
     "Banka Verisi, Tedarikçi'nin global altyapısında ve uygun göreceği veri "
     "merkezlerinde işlenebilir ve saklanabilir.", "DATA_LOCATION"),
    ("SORUMLULUK",
     "Tedarikçi'nin toplam sorumluluğu üç (3) ayda ödenen bedeli aşamaz.",
     "LIMITATION_OF_LIABILITY"),
    ("FESİH",
     "Tedarikçi, sebep göstermeksizin otuz gün önceden bildirimde bulunarak "
     "Sözleşme'yi feshedebilir.", "TERMINATION"),
    ("GÜVENLİK",
     "Tedarikçi, güvenlik ihlalini öğrenmesini müteakip makul bir süre içinde "
     "Banka'ya bildirimde bulunur.", "BREACH_NOTIFICATION"),
    ("MASRAFLAR",
     "İşbu Sözleşme'den doğan damga vergisi Banka tarafından karşılanır.",
     "STAMP_DUTY"),
])
def test_madde_dogru_playbook_tipine_eslesir(baslik, govde, beklenen_kod):
    kodlar = [c["code"] for c in classify(baslik, govde, "SAAS")]
    assert beklenen_kod in kodlar, f"{baslik} yanlış eşleşti: {kodlar}"


def test_boilerplate_madde_yanlis_eslesmez():
    """'MUHTELİF' gibi genel hukumler bir madde tipine zorla baglanmamali."""
    kodlar = classify("MUHTELİF",
                      "İşbu Sözleşme iki nüsha olarak düzenlenmiş olup, "
                      "taraflarca imzalanmıştır.", "SAAS")
    assert not kodlar, f"boilerplate madde eşleşti: {kodlar}"


# --------------------------------------------------------------- yanlış "eksik" beyanı
# Gercek hata: siniflandirma kacagi yuzunden rapor, sozlesmede VAR OLAN maddeler icin
# "sözleşmede yok" diyordu. Toplantida tedarikci avukatinin maddeyi acmasi yeterliydi.

@pytest.mark.parametrize("baslik,govde,beklenen", [
    # m.12.4 - tazminat VAR ve banka aleyhine; "yok" denmemeli
    ("SORUMLULUK",
     "12.4 Banka, Tedarikçi'yi üçüncü kişilerden gelebilecek her türlü talebe karşı "
     "tazmin edecek ve beri kılacaktır.", "INDEMNITY"),
    # m.4 - fiyat artisi VAR ve tek tarafli; "yok" denmemeli
    ("BEDEL VE ÖDEME",
     "Tedarikçi, abonelik ücretlerini her yıl tek taraflı olarak güncelleyebilir.",
     "PRICE_INCREASE"),
])
def test_kirmizi_cizgi_deseni_eslesince_madde_tipi_atanir(baslik, govde, beklenen):
    kodlar = [c["code"] for c in classify(baslik, govde, "SAAS")]
    assert beklenen in kodlar, (
        f"{beklenen} sınıflandırılamadı → rapor bu maddeyi 'sözleşmede yok' "
        f"diye yanlış beyan eder. Bulunan: {kodlar}"
    )


def test_desen_isabeti_zayif_anahtar_skorunu_ezer():
    """Anahtar kelime skoru esigin altinda kalsa bile desen eslesmesi yeterlidir."""
    from app.pipeline.classify import _desen_isabeti, score_clause
    from app.playbook.loader import load_playbook

    govde = "Tedarikçi, abonelik ücretlerini her yıl tek taraflı olarak güncelleyebilir."
    ct = load_playbook()["PRICE_INCREASE"]
    assert _desen_isabeti(govde, ct), "kırmızı çizgi deseni eşleşmedi"
    assert "PRICE_INCREASE" in dict(score_clause("", govde, "SAAS"))


def test_yokluk_bulgusunun_alintisi_kanit_sayilmaz():
    """Yokluk bulgusunda gosterilen metin iddiayi kanitlamaz; baglamdir.

    Kanit gibi sunulursa rapor okuyan hukukcuyu yanlis yonlendirir.
    """
    from app.pipeline.analyze import rule_findings
    from app.pipeline.redlines import evaluate_red_lines
    from app.playbook.loader import load_playbook

    ct = load_playbook()["LIMITATION_OF_LIABILITY"]
    metin = ("Tedarikçi'nin toplam sorumluluğu üç (3) ayda ödenen bedeli aşamaz.")
    hits = evaluate_red_lines(metin, ct)
    bulgular = rule_findings("12.3", ct, hits, [], metin)

    yokluk = [b for b in bulgular if not b.quote_is_evidence]
    desen = [b for b in bulgular if b.quote_is_evidence]
    assert yokluk, "yokluk bulgusu üretilmedi"
    assert desen, "desen bulgusu üretilmedi"
    # Desen bulguları metindeki somut ifadeye dayanır -> alıntı kanıttır
    assert all(b.finding_type in ("RED_LINE", "ONE_SIDED") for b in desen)
    # Yokluk bulguları bir şeyin olmadığını söyler -> alıntı kanıt olamaz
    assert all(b.finding_type == "WEAK" for b in yokluk)


# --------------------------------------------------------------- kapsam boşluğu
# Gercek hata: ACCEPTANCE'in applies_to listesinde SAAS yoktu. Sonuc: SaaS
# sozlesmelerindeki "itiraz edilmezse kabul edilmis sayilir" kirmizi cizgisi
# TAMAMEN gorunmezdi - ne bulgu uretilirdi ne de "eksik" denirdi.

CEKIRDEK_KORUMALAR = [
    "LIMITATION_OF_LIABILITY", "INDEMNITY", "CONFIDENTIALITY", "TERMINATION",
    "GOVERNING_LAW", "AUDIT_RIGHT", "ACCEPTANCE", "PENALTY", "INSURANCE_GUARANTEE",
]


@pytest.mark.parametrize("kod", CEKIRDEK_KORUMALAR)
def test_cekirdek_korumalar_saas_sozlesmelerine_de_uygulanir(kod):
    """Bir madde tipi bir sozlesme tipinden dislanirsa o risk GORUNMEZ olur."""
    pb = load_playbook()
    assert pb[kod].applies("SAAS"), (
        f"{kod} SaaS'a uygulanmıyor → bu risk SaaS sözleşmelerinde hiç aranmayacak"
    )


def test_deemed_acceptance_saas_sozlesmesinde_yakalanir():
    """Sessiz kalma = kabul kaydi, SaaS'ta da kirmizi cizgidir."""
    from app.pipeline.redlines import evaluate_red_lines

    metin = ("Teslim edilen modüllere ilişkin olarak Banka tarafından beş (5) iş günü "
             "içinde yazılı itirazda bulunulmaz ise teslimat kabul edilmiş sayılır.")
    kodlar = [c["code"] for c in classify("KABUL", metin, "SAAS")]
    assert "ACCEPTANCE" in kodlar, f"SaaS'ta kabul maddesi sınıflandırılamadı: {kodlar}"

    ct = load_playbook()["ACCEPTANCE"]
    ids = {h.red_line.id for h in evaluate_red_lines(metin, ct)}
    assert "ACC_DEEMED" in ids, "sessiz kabul kırmızı çizgisi yakalanmadı"
