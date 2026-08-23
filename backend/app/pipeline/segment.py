"""Asama 4: Madde ayristirma.

Analiz birimi maddedir. Chunk degil. Madde siniri anlam sinirdir; bulgunun ankraji
buradan gelir ve eksik madde tespiti ancak madde listesi varsa mumkun olur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_MARK = "[[H]]"

# Turkce ve Ingilizce sozlesmelerde karsilasilan baslik kaliplari.
# Sira onemli: en spesifik olan once denenir.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("madde",   re.compile(r"^\s*MADDE\s+(\d+(?:\.\d+)*)\s*[-–—.:)]?\s*(.*)$", re.IGNORECASE)),
    ("ek",      re.compile(r"^\s*(EK\s*[-–]?\s*\d+|EKLER)\s*[-–—.:)]?\s*(.*)$", re.IGNORECASE)),
    ("article", re.compile(r"^\s*(?:Article|Clause|Section)\s+(\d+(?:\.\d+)*)\s*[-–—.:)]?\s*(.*)$", re.IGNORECASE)),
    ("numeric", re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s*[.)]\s+(.*)$")),
    ("bare",    re.compile(r"^\s*(\d+(?:\.\d+){1,3})\s+(\S.*)$")),
    ("roman",   re.compile(r"^\s*([IVXLC]{1,6})\s*[.)]\s+(\S.*)$")),
]

# Bir satirin baslik SAYILMASINI engelleyen durumlar (yanlis pozitif frenleri).
# Dar tutulur: fazla genis bir fren gercek alt maddeleri (12.3 gibi) sessizce yutar.
_FALSE_HEAD = re.compile(
    r"^\s*(?:"
    r"\d{1,2}[./]\d{1,2}[./]\d{2,4}\b"                     # tarih: 01.01.2026
    r"|\d+(?:[.,]\d{3})*(?:[.,]\d+)?\s*(?:%|TL|USD|EUR|\u20ba|\$)"  # tutar / oran
    r"|\d+\s*$"                                             # yalniz numara
    r")",
    re.IGNORECASE,
)

MAX_HEADING_LEN = 160


@dataclass
class RawClause:
    number: str
    heading: str
    text: str = ""
    level: int = 1
    char_start: int = 0
    char_end: int = 0
    order_index: int = 0
    kind: str = "madde"
    children: list = field(default_factory=list)


def _match_heading(line: str) -> tuple[str, str, str] | None:
    """(kind, number, heading) veya None."""
    stripped = line.strip()
    if not stripped or len(stripped) > 400:
        return None
    forced = stripped.startswith(HEADING_MARK)
    if forced:
        stripped = stripped[len(HEADING_MARK):].strip()
    if _FALSE_HEAD.match(stripped):
        return None

    for kind, pat in PATTERNS:
        m = pat.match(stripped)
        if not m:
            continue
        number = (m.group(1) or "").strip()
        heading = (m.group(2) or "").strip()

        if kind in ("numeric", "bare", "roman"):
            # Cok uzun ya da cumle gibi devam eden satirlar baslik degildir;
            # ancak DOCX stili bunu baslik diye isaretlediyse guveniriz.
            if not forced:
                if len(heading) > MAX_HEADING_LEN:
                    continue
                if kind == "numeric" and "." not in number and not _looks_titleish(heading):
                    continue
                if kind == "roman" and not _looks_titleish(heading):
                    continue
        return kind, number, heading
    return None


def _looks_titleish(s: str) -> bool:
    """Baslik gibi mi: kisa, cumle sonu noktalamasi yok, buyuk harf agirlikli."""
    if not s or len(s) > MAX_HEADING_LEN:
        return False
    if s.endswith((".", ";", ",")):
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper_ratio > 0.55 or (s[0].isupper() and len(s.split()) <= 12)


def _level_of(number: str, kind: str) -> int:
    if kind == "ek":
        return 1
    return number.count(".") + 1


def segment(text: str) -> list[RawClause]:
    """Normalize edilmis metni maddelere boler; offsetler bu metne goredir."""
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1

    heads: list[tuple[int, str, str, str]] = []  # (line_idx, kind, number, heading)
    for i, ln in enumerate(lines):
        hit = _match_heading(ln)
        if hit:
            heads.append((i, *hit))

    if len(heads) < 3:
        return _fallback_paragraphs(text)

    clauses: list[RawClause] = []
    for idx, (line_idx, kind, number, heading) in enumerate(heads):
        start = offsets[line_idx]
        end = offsets[heads[idx + 1][0]] if idx + 1 < len(heads) else len(text)
        body = text[start:end].strip()
        clauses.append(
            RawClause(
                number=number,
                heading=heading[:400],
                text=body,
                level=_level_of(number, kind),
                char_start=start,
                char_end=end,
                order_index=idx,
                kind=kind,
            )
        )

    # Cok kisa govdeli ardisik basliklar (ornegin baslik + alt baslik) birlestirilir.
    merged: list[RawClause] = []
    for c in clauses:
        if merged and len(c.text) < 40 and len(merged[-1].text) < 40:
            prev = merged[-1]
            prev.text = (prev.text + "\n" + c.text).strip()
            prev.char_end = c.char_end
            continue
        merged.append(c)
    for i, c in enumerate(merged):
        c.order_index = i
    return merged


def _fallback_paragraphs(text: str) -> list[RawClause]:
    """Baslik bulunamadi: bos satirla ayrilan paragraflari madde say.

    Ideal degil ama analizi tamamen durdurmaktan iyidir; kullaniciya uyari gosterilir.
    """
    out: list[RawClause] = []
    pos = 0
    for block in re.split(r"\n\s*\n", text):
        raw_len = len(block)
        if block.strip() and len(block.strip()) > 80:
            start = text.find(block, pos)
            if start < 0:
                start = pos
            out.append(
                RawClause(
                    number=str(len(out) + 1),
                    heading="",
                    text=block.strip(),
                    level=1,
                    char_start=start,
                    char_end=start + raw_len,
                    order_index=len(out),
                    kind="paragraf",
                )
            )
            pos = start + raw_len
    return out
