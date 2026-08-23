"""Asama 3: Normalizasyon.

Kural: normalize edilmis metin, madde sinirlarinin ve alintilarin referans metnidir.
Bu yuzden agresif degil dikkatli temizlenir - silinen her karakter bir alintiyi bozabilir.
"""
from __future__ import annotations

import re
from collections import Counter

SOFT_HYPHEN = "\u00ad"
NBSP = "\u00a0"


def normalize(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(SOFT_HYPHEN, "")
    text = text.replace(NBSP, " ")
    text = re.sub(r"[ \t]+", " ", text)

    lines = [ln.rstrip() for ln in text.split("\n")]
    lines = _drop_repeating_furniture(lines)
    lines = _dehyphenate(lines)

    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _drop_repeating_furniture(lines: list[str]) -> list[str]:
    """Her sayfada tekrar eden ustbilgi/altbilgi ve sayfa numaralarini at.

    Dikkatli olmak zorundayiz: burada silinen her satir, sonradan bir alintinin
    dogrulanamamasina yol acar. Bu yuzden yalnizca ustbilgi/altbilgi GORUNUMLU
    satirlar elenir - cumle gibi duran veya uzun satirlara dokunulmaz.
    """
    counts = Counter(ln.strip() for ln in lines if 3 < len(ln.strip()) < 90)
    threshold = max(4, len(lines) // 120)
    noisy = {
        t for t, c in counts.items()
        if c >= threshold and not _looks_like_content(t) and _looks_like_furniture(t)
    }

    kept = []
    for ln in lines:
        s = ln.strip()
        if s and s in noisy:
            continue
        if re.fullmatch(r"-?\s*(sayfa\s*)?\d{1,3}\s*(/\s*\d{1,3})?\s*-?", s, re.IGNORECASE):
            continue
        kept.append(ln)
    return kept


def _looks_like_furniture(s: str) -> bool:
    """Ustbilgi/altbilgi gorunumu: kisa, cumle degil, noktalama ile bitmiyor.

    "Gizli - Ornek Bankasi A.S." ustbilgidir; "Taraflar bu maddeye uymayi kabul eder."
    cumledir ve kac kez tekrarlanirsa tekrarlansin silinmez.
    """
    s = s.strip()
    if len(s) > 70 or len(s.split()) > 9:
        return False
    if s.endswith(("!", "?", ":", ";")):
        return False
    # Nokta ile bitmek tek basina cumle demek degildir: "Ornek Bankasi A.S." bir
    # ustbilgidir, "...kabul ve taahhut eder." bir cumledir. Ayirt edici olan,
    # son kelimenin kisaltma mi yoksa cekimli bir sozcuk mu oldugudur.
    m = re.search(r"(\w+)\.$", s)
    if m:
        son = m.group(1)
        if len(son) >= 3 and son == son.lower():
            return False
    return True


def _looks_like_content(s: str) -> bool:
    """Madde basligina benzeyen tekrarlar korunur (yanlislikla silmeyelim)."""
    return bool(re.match(r"^\s*(madde|article|ek)\s*[-\s]*\d", s, re.IGNORECASE))


def _dehyphenate(lines: list[str]) -> list[str]:
    """Satir sonu tirelemesini birlestir."""
    out: list[str] = []
    skip = False
    for i, ln in enumerate(lines):
        if skip:
            skip = False
            continue
        m = re.search(r"(\w+)-$", ln)
        if m and i + 1 < len(lines):
            nxt = lines[i + 1].lstrip()
            if nxt and nxt[0].islower():
                out.append(ln[: m.start(1)] + m.group(1) + nxt)
                skip = True
                continue
        out.append(ln)
    return out
