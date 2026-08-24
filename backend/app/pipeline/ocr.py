"""OCR — taranmis belgeler icin metin katmani uretimi.

Ne zaman devreye girer: PDF'in kendi metin katmani yetersizse (taranmis belge).
Karar deterministiktir: sayfa basina dusen okunabilir karakter sayisi esigin altindaysa.

Bagimliliklar sistemde yoksa OCR SESSIZCE ATLANMAZ; kullaniciya ne kurulmasi
gerektigini soyleyen net bir hata dondurulur. Yanlis analiz, analiz yapmamaktan kotudur.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

# Sayfa basina bu kadar karakterin altindaysa metin katmani "yok" sayilir.
MIN_CHARS_PER_PAGE = 120
# OCR ciktisinin kabul edilmesi icin gereken asgari kalite.
MIN_OCR_CHARS_PER_PAGE = 60


class OCRUnavailable(RuntimeError):
    """OCR gerekli ama sistemde kurulu degil."""


@dataclass
class OCRSonuc:
    text: str
    pages: list[dict]
    used: bool
    engine: str = ""
    mean_confidence: float | None = None
    note: str = ""


def metin_katmani_yetersiz(text: str, page_count: int) -> bool:
    """Bu PDF taranmis mi? Deterministik karar."""
    if page_count <= 0:
        return True
    okunabilir = len(re.sub(r"\s", "", text or ""))
    return (okunabilir / page_count) < MIN_CHARS_PER_PAGE


def kullanilabilir() -> tuple[bool, str]:
    """(hazir_mi, aciklama)"""
    if not settings.ocr_enabled:
        return False, "OCR yapılandırmayla kapatılmış (OCR_ENABLED=0)"
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "pytesseract paketi kurulu değil"
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False, "pymupdf paketi kurulu değil"
    if not shutil.which(settings.tesseract_cmd):
        return False, f"tesseract çalıştırılabiliri bulunamadı ({settings.tesseract_cmd})"
    return True, "hazır"


def diller() -> list[str]:
    try:
        import pytesseract

        return list(pytesseract.get_languages(config=""))
    except Exception:
        return []


def _dil_secimi() -> str:
    """Istenen diller kurulu degilse kurulu olanlara duser."""
    istenen = [d for d in settings.ocr_lang.split("+") if d]
    kurulu = set(diller())
    if not kurulu:
        return settings.ocr_lang
    secili = [d for d in istenen if d in kurulu]
    if not secili:
        secili = ["eng"] if "eng" in kurulu else [sorted(kurulu)[0]]
        log.warning("OCR dilleri %s kurulu değil; %s kullanılıyor", istenen, secili)
    return "+".join(secili)


def pdf_ocr(path: str | Path) -> OCRSonuc:
    """PDF sayfalarini goruntuye cevirip OCR uygular."""
    hazir, neden = kullanilabilir()
    if not hazir:
        raise OCRUnavailable(neden)

    import pymupdf
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = shutil.which(settings.tesseract_cmd) or settings.tesseract_cmd
    lang = _dil_secimi()
    zoom = settings.ocr_dpi / 72.0

    parcalar: list[str] = []
    pages: list[dict] = []
    guvenler: list[float] = []
    cursor = 0

    with pymupdf.open(str(path)) as belge:
        toplam = belge.page_count
        limit = min(toplam, settings.ocr_max_pages) if settings.ocr_max_pages else toplam
        if limit < toplam:
            log.warning("OCR sayfa sınırı: %d/%d sayfa işlenecek", limit, toplam)

        for i in range(limit):
            sayfa = belge.load_page(i)
            pix = sayfa.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            try:
                metin = pytesseract.image_to_string(img, lang=lang) or ""
            except Exception as exc:  # tek sayfa tum belgeyi dusurmesin
                log.warning("OCR sayfa %d başarısız: %s", i + 1, exc)
                metin = ""
            try:
                veri = pytesseract.image_to_data(
                    img, lang=lang, output_type=pytesseract.Output.DICT
                )
                sayfa_guven = [float(c) for c in veri.get("conf", []) if str(c).lstrip("-").isdigit() and float(c) >= 0]
                if sayfa_guven:
                    guvenler.append(sum(sayfa_guven) / len(sayfa_guven))
            except Exception:
                pass

            metin = metin.replace("\r\n", "\n")
            parcalar.append(metin)
            pages.append({"page": i + 1, "start": cursor, "end": cursor + len(metin)})
            cursor += len(metin) + 1

    text = "\n".join(parcalar)
    ortalama = round(sum(guvenler) / len(guvenler), 1) if guvenler else None

    okunabilir = len(re.sub(r"\s", "", text))
    if pages and (okunabilir / len(pages)) < MIN_OCR_CHARS_PER_PAGE:
        raise OCRUnavailable(
            f"OCR anlamlı metin üretemedi (sayfa başına {okunabilir // max(len(pages),1)} karakter). "
            "Belge çözünürlüğü düşük veya el yazısı olabilir."
        )

    not_ = f"OCR uygulandı (tesseract, dil={lang}, {settings.ocr_dpi} dpi, {len(pages)} sayfa)"
    if ortalama is not None:
        not_ += f", ortalama güven %{ortalama:.0f}"
    return OCRSonuc(text=text, pages=pages, used=True, engine=f"tesseract:{lang}",
                    mean_confidence=ortalama, note=not_)
