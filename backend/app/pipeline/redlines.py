"""Deterministik hedefleyiciler.

Bunlar "analiz" degil, MODELE HEDEF GOSTEREN katmandir (bkz. docs/08).
Model yoksa ayni ciktilar dogrudan kural tabanli bulguya donusur; model varsa
prompta kontrol listesi olarak zerk edilir (K2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..playbook.loader import ClauseType, RedLine
from ..textutil import deaccent, fold, tr_lower

# Olculemez ifadeler sozlugu (docs/01 §7). Gectigi madde AMBIGUOUS adayidir.
AMBIGUOUS_PHRASES = [
    "makul çaba", "makul gayret", "makul özen", "ticari makul", "ticari olarak makul",
    "en iyi çaba", "en iyi gayret", "gerektiğinde", "mümkün olan en kısa sürede",
    "makul bir süre", "makul süre içinde", "uygun gördüğü takdirde",
    "uygun görülmesi hâlinde", "uygun görülmesi halinde", "zaman zaman",
    "önemli ölçüde", "esaslı ölçüde", "derhal", "ivedilikle", "gecikmeksizin",
    "ve benzeri", "dilediği gibi", "tek taraflı olarak", "bildirimde bulunmaksızın",
    "onay almaksızın", "kendi takdirine göre", "makul olmayan şekilde",
]

_CROSSREF = re.compile(r"\bEK\s*[-–]?\s*(\d+)", re.IGNORECASE)


@dataclass
class RedLineHit:
    red_line: RedLine
    quote: str
    start: int
    end: int
    kind: str  # "PATTERN" | "ABSENCE"


def _norm_for_match(s: str) -> str:
    """Regex kaliplari kucuk harfli Turkce metne gore yazildi."""
    return tr_lower(s)


def evaluate_red_lines(
    clause_text: str,
    ct: ClauseType,
    scope_text: str | None = None,
    include_absence: bool = True,
) -> list[RedLineHit]:
    """Bu maddede playbook kirmizi cizgilerinden hangileri ihlal edilmis?

    Onemli ayrim:
      - PATTERN kurallari MADDE metnine bakar ("bu maddede kotu bir ifade var mi?").
      - ABSENCE kurallari SOZLESMENIN o madde tipine ait TUM metnine bakar
        ("bu koruma hicbir yerde yok mu?"). Aksi halde ayni eksiklik, ayni koda sahip
        her madde icin tekrar tekrar raporlanir.
    """
    hay = _norm_for_match(clause_text)
    hay_scope = _norm_for_match(scope_text if scope_text is not None else clause_text)
    hits: list[RedLineHit] = []

    for rl in ct.red_lines:
        if rl.patterns:
            for pat in rl.patterns:
                m = pat.search(hay)
                if m:
                    start, end = _expand_to_sentence(clause_text, m.start(), m.end())
                    hits.append(
                        RedLineHit(
                            red_line=rl,
                            quote=clause_text[start:end].strip(),
                            start=start,
                            end=end,
                            kind="PATTERN",
                        )
                    )
                    break
        elif rl.absent_patterns:
            if not include_absence:
                continue
            # Bu kaliplarin HICBIRI yoksa ihlal: olmasi gereken koruma eksik.
            if not any(p.search(hay_scope) for p in rl.absent_patterns):
                start, end = _first_sentence(clause_text)
                hits.append(
                    RedLineHit(
                        red_line=rl,
                        quote=clause_text[start:end].strip(),
                        start=start,
                        end=end,
                        kind="ABSENCE",
                    )
                )
    return hits


def _expand_to_sentence(text: str, start: int, end: int, max_len: int = 420) -> tuple[int, int]:
    """Eslesmeyi iceren cumleyi alinti olarak dondur - baglamsiz alinti yanlis anlasilir."""
    left = max(0, start - max_len)
    seg = text[left:start]
    for sep in (". ", ".\n", "\n\n", "; "):
        idx = seg.rfind(sep)
        if idx >= 0:
            left = left + idx + len(sep)
            break
    else:
        left = max(0, start - 160)

    right = min(len(text), end + max_len)
    seg2 = text[end:right]
    m = re.search(r"[.;]\s|\n\n", seg2)
    right = end + (m.end() if m else min(len(seg2), 200))
    right = min(right, len(text))
    return left, right


def _first_sentence(text: str, limit: int = 300) -> tuple[int, int]:
    body = text.strip()
    offset = text.find(body) if body else 0
    m = re.search(r"[.;]\s", body[:limit])
    end = offset + (m.end() if m else min(len(body), limit))
    return offset, min(end, len(text))


def find_ambiguous(clause_text: str) -> list[tuple[str, int, int]]:
    """(ifade, start, end) - olculemez ifade gecisleri.

    Iki tur: once birebir, sonra aksansiz. Bazi sozlesmeler Turkce karakter
    kullanmadan yazilir ("makul bir sure"); bunlar da yakalanmalidir.
    """
    hay = fold(clause_text)
    hay_flat = deaccent(clause_text)
    found: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for phrase in AMBIGUOUS_PHRASES:
        p = fold(phrase)
        idx = hay.find(p)
        if idx < 0:
            pf = deaccent(phrase)
            if pf in hay_flat:
                p = pf
                idx = hay_flat.find(pf)
            else:
                continue
        if phrase in seen:
            continue
        seen.add(phrase)
        # Katlanmis metindeki konumu kaba da olsa orijinale tasi.
        approx = _approx_index(clause_text, p)
        if approx is None:
            continue
        s, e = _expand_to_sentence(clause_text, approx, approx + len(p))
        found.append((phrase, s, e))
    return found


def _approx_index(original: str, folded_needle: str) -> int | None:
    low = fold(original)
    idx = low.find(folded_needle)
    if idx < 0:
        low = deaccent(original)
        idx = low.find(folded_needle)
    if idx < 0:
        return None
    # Katlama yalnizca bosluk daraltmasi yapar; kisa metinlerde sapma ihmal edilebilir.
    ratio = len(original) / max(len(low), 1)
    approx = int(idx * ratio)
    return max(0, min(approx, len(original) - 1))


def missing_annex_refs(full_text: str) -> list[str]:
    """Metinde atif yapilan ama basligi bulunmayan ekler."""
    refs = {m.group(1) for m in _CROSSREF.finditer(full_text)}
    present = set()
    for m in re.finditer(r"^\s*EK\s*[-–]?\s*(\d+)", full_text, re.IGNORECASE | re.MULTILINE):
        present.add(m.group(1))
    return sorted(refs - present, key=lambda x: int(x))
