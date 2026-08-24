"""Örnek sözleşmeyi 5 sayfalık PDF'e çevirir (test verisi üretimi).

    python samples/pdf_uret.py [kaynak.txt] [hedef.pdf]

Türkçe karakterler için sistemde bulunan bir Unicode TTF font kaydedilir.
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

FONT_ADAYLARI = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def font_kaydet() -> str:
    for yol in FONT_ADAYLARI:
        if Path(yol).exists():
            pdfmetrics.registerFont(TTFont("Govde", yol))
            return "Govde"
    print("UYARI: Unicode font bulunamadı, Türkçe karakterler bozulabilir", file=sys.stderr)
    return "Helvetica"


def uret(kaynak: Path, hedef: Path) -> None:
    font = font_kaydet()
    metin = kaynak.read_text(encoding="utf-8")

    ss = getSampleStyleSheet()
    baslik = ParagraphStyle("Baslik", parent=ss["Title"], fontName=font, fontSize=15,
                            leading=20, spaceAfter=10)
    madde = ParagraphStyle("Madde", parent=ss["Heading2"], fontName=font, fontSize=10.5,
                           leading=14, spaceBefore=9, spaceAfter=3)
    govde = ParagraphStyle("Govde", parent=ss["BodyText"], fontName=font, fontSize=9,
                           leading=12.5, spaceAfter=5, alignment=4)  # justify

    doc = SimpleDocTemplate(
        str(hedef), pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title="Yazılım Hizmeti Tedarik Sözleşmesi",
    )

    akis = []
    for ham in metin.split("\n\n"):
        blok = ham.strip()
        if not blok:
            continue
        satirlar = blok.split("\n")
        ilk = satirlar[0].strip()
        if ilk.upper().startswith(("MADDE", "EK-")):
            akis.append(Paragraph(_kacir(ilk), madde))
            kalan = " ".join(s.strip() for s in satirlar[1:]).strip()
            if kalan:
                akis.append(Paragraph(_kacir(kalan), govde))
        elif len(akis) == 0:
            akis.append(Paragraph(_kacir(blok.replace("\n", " ")), baslik))
            akis.append(Spacer(1, 4 * mm))
        else:
            akis.append(Paragraph(_kacir(blok.replace("\n", " ")), govde))

    doc.build(akis)


def _kacir(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    kaynak = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "ornek-saas-sozlesmesi.txt"
    hedef = Path(sys.argv[2]) if len(sys.argv) > 2 else kaynak.with_suffix(".pdf")
    uret(kaynak, hedef)
    print(f"üretildi: {hedef} ({hedef.stat().st_size/1024:.0f} KB)")
