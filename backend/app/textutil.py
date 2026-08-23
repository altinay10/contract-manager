"""Türkçe metin yardımcıları.

Python'un varsayılan .lower() metodu 'İ' harfini birleşik noktalı 'i̇' hâline getirir;
bu, regex eşleşmelerini sessizce bozar. Bu yüzden kendi katlama fonksiyonumuz var.
"""
from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})


def tr_lower(s: str) -> str:
    """Türkçeye uygun küçük harfe çevirme."""
    return s.translate(_TR_MAP).lower()


def fold(s: str) -> str:
    """Eşleştirme için normalize: küçük harf + tek boşluk + tırnak sadeleştirme."""
    s = tr_lower(s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


_QUOTE_MAP = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}


def _fold_char(ch: str) -> str:
    """Tek karakteri eşleştirme biçimine indirger (boşluk çağıranın sorumluluğunda)."""
    ch = _QUOTE_MAP.get(ch, ch)
    return tr_lower(ch)


def deaccent(s: str) -> str:
    """Aksan/işaret kaldırma — yalnız gevşek arama için."""
    n = unicodedata.normalize("NFD", tr_lower(s))
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def find_quote(haystack: str, needle: str) -> tuple[int, int] | None:
    """Alıntının metinde birebir (boşluk toleranslı) yerini bul.

    Grounding doğrulamasının çekirdeği: model bir alıntı iddia ediyorsa, o alıntının
    kaynak metinde gerçekten bulunması gerekir. Bulunamazsa bulgu düşürülür.
    """
    if not needle or not haystack:
        return None
    needle = needle.strip().strip('"').strip("«»").strip("“”")
    if len(needle) < 12:
        return None

    # 1) doğrudan
    idx = haystack.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)

    # 2) katlanmış metinde, orijinal indekse geri haritalayarak
    folded_chars: list[str] = []
    index_map: list[int] = []
    prev_space = False
    for i, ch in enumerate(haystack):
        if ch.isspace() or ch == "\u00a0":
            if prev_space:
                continue
            prev_space = True
            folded_chars.append(" ")
            index_map.append(i)
            continue
        prev_space = False
        folded_chars.append(_fold_char(ch))
        index_map.append(i)
    folded = "".join(folded_chars).strip()
    # strip() baştaki boşlukları attıysa index_map ile hizayı koru
    lead = len("".join(folded_chars)) - len("".join(folded_chars).lstrip())
    if lead:
        index_map = index_map[lead:]
    fneedle = fold(needle)
    j = folded.find(fneedle)
    if j < 0:
        return None
    start = index_map[j]
    end_idx = min(j + len(fneedle) - 1, len(index_map) - 1)
    return start, index_map[end_idx] + 1


def snippet(text: str, start: int, end: int, pad: int = 0) -> str:
    return text[max(0, start - pad): min(len(text), end + pad)].strip()
