"""Asama 5: Meta cikarimi (taraflar, bedel, sure, damga vergisi yukumlusu).

Deterministik regex katmani. Model varsa dogrulanabilir; yoksa da calisir.
"""
from __future__ import annotations

import re

from ..textutil import fold

_AMOUNT = re.compile(
    r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*"
    r"(TL|TRY|USD|EUR|€|\$|₺|Amerikan Dolar[ıi]|Avro|T[uü]rk Liras[ıi])",
    re.IGNORECASE,
)
_TERM = re.compile(
    r"(\d+|bir|iki|üç|uc|dört|dort|beş|bes|altı|alti|on iki|oniki|yirmi dört|yirmidort|otuz altı)"
    r"\s*\(?\s*\d*\s*\)?\s*\b(yıl|yil|ay)[a-zçğıöşü]{0,5}\b",
    re.IGNORECASE,
)
_PARTY = re.compile(
    r"([A-ZÇĞİÖŞÜ][\w\.\-&'’ ]{2,60}?\s*"
    r"(?:A\.?Ş\.?|Ltd\.?\s*Şti\.?|LTD|LLC|GmbH|Inc\.?|B\.?V\.?|S\.?A\.?))",
)
_BANK_HINT = re.compile(r"bank", re.IGNORECASE)

_WORD_NUM = {
    "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5, "bes": 5,
    "altı": 6, "alti": 6, "on iki": 12, "oniki": 12, "yirmi dört": 24, "yirmidort": 24,
    "otuz altı": 36,
}


def extract_meta(text: str) -> dict:
    head = text[:6000]
    out: dict = {}

    parties = []
    for m in _PARTY.finditer(head):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
        name = _strip_lead(name)
        if name and len(name) > 3 and name not in parties:
            parties.append(name)
    out["parties"] = parties[:6]
    counter = next((p for p in parties if not _BANK_HINT.search(p)), "")
    out["counterparty"] = counter

    m = _AMOUNT.search(text)
    out["value_text"] = f"{m.group(1)} {m.group(2)}".strip() if m else ""

    tm = _pick_term(text)
    if tm:
        raw = fold(tm.group(1))
        n = _WORD_NUM.get(raw, None)
        if n is None:
            try:
                n = int(raw)
            except ValueError:
                n = None
        unit = "yıl" if fold(tm.group(2)).startswith(("yil", "yıl")) else "ay"
        out["term_text"] = f"{n} {unit}" if n else tm.group(0).strip()
    else:
        out["term_text"] = ""

    low = fold(text)
    if "damga vergisi" in low:
        seg_start = low.find("damga vergisi")
        seg = text[max(0, seg_start - 200): seg_start + 300]
        seg_low = fold(seg)
        # Alici tarafin adi "banka" olmak zorunda degil; sozlesmedeki gercek
        # tanimli terimlerle ara. Aksi halde damga vergisi yuku alici tarafa
        # yiklenmis olsa bile risk olarak isaretlenmezdi.
        from .parties import alici_adlari
        alici_izi = any(a in seg_low for a in alici_adlari(text))
        if alici_izi and "eşit" not in seg_low and "esit" not in seg_low:
            out["stamp_duty"] = "Alıcıya ait (risk)"
        elif "eşit" in seg_low or "esit" in seg_low or "yarı" in seg_low:
            out["stamp_duty"] = "Eşit paylaşım"
        else:
            out["stamp_duty"] = "Belirtilmiş (elle kontrol)"
    else:
        out["stamp_duty"] = "Sözleşmede düzenlenmemiş"

    out["auto_renew"] = bool(re.search(r"(kendiliğinden|otomatik olarak)[^.]{0,40}(yenilen|uzar)", low))
    return out


_LEAD_WORDS = re.compile(
    r"^(?:işbu|isbu|bir\s+taraftan|diğer\s+taraftan|diger\s+taraftan|sözleşme|sozlesme|"
    r"taraflar|ile|ve|arasında|arasinda)\b[\s:]*",
    re.IGNORECASE,
)


def _strip_lead(name: str) -> str:
    """Taraf adinin basindaki kalip kelimeleri at ('Isbu sozlesme Ornek Bankasi A.S.')."""
    prev = None
    while prev != name:
        prev = name
        name = _LEAD_WORDS.sub("", name).strip(" .,-")
    return name


def _pick_term(text: str):
    """Sozlesme suresini secerken 'sure' baglamina yakin eslesmeyi tercih et.

    Otomatik yenileme cumlesindeki 'bir yil uzar' ifadesi sozlesme suresi degildir.
    """
    matches = list(_TERM.finditer(text))
    if not matches:
        return None
    for m in matches:
        ctx = fold(text[max(0, m.start() - 90): m.end() + 40])
        if "süre" in ctx or "sure" in ctx or "geçerli" in ctx or "gecerli" in ctx:
            if "uzar" in ctx or "yenilen" in ctx:
                continue
            return m
    for m in matches:
        ctx = fold(text[max(0, m.start() - 60): m.end() + 30])
        if "uzar" not in ctx and "yenilen" not in ctx:
            return m
    return matches[0]
