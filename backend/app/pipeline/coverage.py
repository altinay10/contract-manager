"""Kapsama katmanı — metnin her karakteri bir birime ait olsun.

`segment()` madde başlıklarını arar ve bulduklarını maddelere böler. Ama
metnin bir kısmı hiçbir maddeye girmez:

* **Preamble** — ilk başlıktan önceki her şey. Sözleşmenin adı, tarafları ve
  tarihi burada. Ölçüm (samples/ornek-saas-sozlesmesi.pdf): 4.496 karakterin
  224'ü, yani %5'i.
* **Yedek mod kayıpları** — belgede 3'ten az başlık tanınırsa `segment()`
  paragraf moduna düşer ve 80 karakterden kısa blokları tamamen atar.
  Ölçüm: "Bedel: 250.000 TL." (18 karakter) yok oldu.

Karşılaştırmada bu kabul edilemez: gösterilmeyen bir değişiklik, olmayan bir
değişiklikten ayırt edilemez. Bu modül `segment()` çıktısını alır ve
kapsanmayan her aralığı kendi birimine dönüştürür.

`segment()` DEĞİŞTİRİLMEZ — onu değiştirmek analiz hattının davranışını da
değiştirirdi. Boşluk burada, karşılaştırma tarafında doldurulur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .segment import RawClause, segment

# Bir boşluk biriminin madde sayılabilmesi için gereken en az anlamlı karakter.
# Yalnız boşluk/satır sonundan ibaret aralıklar birim üretmez.
MIN_GAP_CHARS = 2


@dataclass
class Unit:
    """Karşılaştırmanın atomu. Madde de olabilir, boşluktan türemiş de."""
    number: str
    heading: str
    text: str
    char_start: int
    char_end: int
    order_index: int = 0
    is_gap: bool = False


def _gap_label(text: str, is_first: bool, is_last: bool) -> tuple[str, str]:
    """Boşluk birimine insan okur bir ad ver: (number, heading)."""
    ilk_satir = next((s.strip() for s in text.split("\n") if s.strip()), "")
    if is_first:
        return ("", "Başlık ve taraflar")
    if is_last and re.search(r"\bimza|\bkaşe|\bmühür", text, re.IGNORECASE):
        return ("", "İmza bloğu")
    return ("", ilk_satir[:80] or "Madde dışı metin")


def build_units(text: str) -> list[Unit]:
    """Metni, TAMAMINI kapsayan birimlere böler.

    Dönen birimlerin aralıkları birleştiğinde [0, len(text)) elde edilir.
    `verify_coverage` bunu doğrular.
    """
    clauses: list[RawClause] = segment(text)
    # Aralıkları sırala ve metin sınırlarına kırp.
    parcalar = sorted(
        ((max(0, c.char_start), min(len(text), c.char_end), c) for c in clauses),
        key=lambda t: (t[0], t[1]),
    )

    birimler: list[tuple[int, int, RawClause | None]] = []
    imlec = 0
    for start, end, c in parcalar:
        if end <= start:
            continue
        # segment() teorik olarak çakışmayan aralıklar üretir; yine de
        # savunmacı davran: çakışma varsa öncekinin bittiği yerden başla.
        start = max(start, imlec)
        if end <= start:
            continue
        if start > imlec:
            birimler.append((imlec, start, None))     # boşluk
        birimler.append((start, end, c))
        imlec = end
    if imlec < len(text):
        birimler.append((imlec, len(text), None))     # sondaki boşluk

    out: list[Unit] = []
    for i, (start, end, c) in enumerate(birimler):
        govde = text[start:end]
        if c is None:
            if len(govde.strip()) < MIN_GAP_CHARS:
                # Anlamsız aralık kendi birimini hak etmiyor; bir öncekine ekle.
                # Hiç birim yoksa (metnin başıysa) sonrakine bırakılır.
                if out:
                    out[-1].text = text[out[-1].char_start:end]
                    out[-1].char_end = end
                    continue
            no, baslik = _gap_label(govde, is_first=(start == 0),
                                    is_last=(end == len(text)))
            out.append(Unit(number=no, heading=baslik, text=govde.strip(),
                            char_start=start, char_end=end, is_gap=True))
        else:
            out.append(Unit(number=c.number, heading=c.heading, text=govde.strip(),
                            char_start=start, char_end=end, is_gap=False))

    # Baştaki anlamsız aralık hiçbir birime eklenememişse sonrakine yapıştır.
    if len(out) >= 2 and out[0].is_gap and len(out[0].text) < MIN_GAP_CHARS:
        out[1].char_start = out[0].char_start
        out[1].text = text[out[1].char_start:out[1].char_end].strip()
        out.pop(0)

    for i, u in enumerate(out):
        u.order_index = i
    return out


def verify_coverage(text: str, units: list[Unit]) -> None:
    """Birimler metnin tamamını kapsıyor mu? Kapsamıyorsa hata fırlatır.

    Bu bir iyimserlik kontrolü değil, karşılaştırmanın ön koşulu. Kapsam tam
    değilse gösterilmeyen bir değişiklik olabilir demektir; o hâlde
    karşılaştırma hiç başlamamalıdır.
    """
    if not text:
        return
    if not units:
        raise ValueError("Metin boş değil ama hiç birim üretilmedi")

    imlec = 0
    for u in sorted(units, key=lambda x: x.char_start):
        if u.char_start > imlec:
            eksik = text[imlec:u.char_start]
            raise ValueError(
                f"Kapsama boşluğu: {imlec}-{u.char_start} "
                f"({len(eksik)} karakter) hiçbir birime ait değil: {eksik[:120]!r}"
            )
        imlec = max(imlec, u.char_end)
    if imlec < len(text):
        raise ValueError(
            f"Kapsama boşluğu: metnin sonu {imlec}-{len(text)} "
            f"({len(text) - imlec} karakter) hiçbir birime ait değil"
        )


def units_of(text: str) -> list[Unit]:
    """build_units + verify_coverage. Karşılaştırma bunu çağırır."""
    u = build_units(text)
    verify_coverage(text, u)
    return u
