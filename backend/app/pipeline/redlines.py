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
# Olculemez ifadeler IKI SINIFA ayrilir. Hepsini ayni sekilde isaretlemek raporu
# gurultuye bogar: gercek vakada 39 bulgunun 25'i "derhal" gibi kelimelerdi ve
# gercek riskleri gorunmez kildi.
#
# ZAYIFLATICI  : bankanin elini zayiflatir; nerede gecerse gecsin risktir.
# BELIRSIZ_SURE: sure belirsizligidir; YALNIZCA sureye bagli maddelerde anlamlidir.
#                "Tedarikci derhal bildirir" bankanin lehinedir, kusur degildir.
ZAYIFLATICI = [
    "makul çaba", "makul gayret", "makul özen", "ticari makul", "ticari olarak makul",
    "en iyi çaba", "en iyi gayret", "uygun gördüğü takdirde",
    "uygun görülmesi hâlinde", "uygun görülmesi halinde", "zaman zaman",
    "önemli ölçüde", "esaslı ölçüde", "ve benzeri", "dilediği gibi",
    "tek taraflı olarak", "bildirimde bulunmaksızın", "onay almaksızın",
    "kendi takdirine göre", "makul olmayan şekilde", "gerektiğinde",
]

BELIRSIZ_SURE = [
    "derhal", "ivedilikle", "gecikmeksizin", "mümkün olan en kısa sürede",
    "makul bir süre", "makul süre içinde", "en kısa sürede",
]

# Sure belirsizliginin gercekten risk oldugu madde tipleri.
SURE_HASSAS_KODLAR = {
    "BREACH_NOTIFICATION", "SLA", "ACCEPTANCE", "EXIT_TRANSITION",
    "WARRANTY_MAINTENANCE", "PAYMENT_TERMS", "CHANGE_MANAGEMENT",
    "BUSINESS_CONTINUITY", "SECURITY_TESTING", "TERMINATION",
}

AMBIGUOUS_PHRASES = ZAYIFLATICI + BELIRSIZ_SURE


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


def _uygula_alici(pat: re.Pattern, alici: str | None) -> re.Pattern:
    """Desendeki {ALICI} yer tutucusunu sozlesmedeki alici adlariyla doldurur."""
    if not alici or "{ALICI}" not in pat.pattern:
        # Yer tutucu doldurulmadiysa varsayilan adlarla calis (banka, musteri...).
        if "{ALICI}" in pat.pattern:
            from .parties import VARSAYILAN_ALICI
            alici = "(?:" + "|".join(VARSAYILAN_ALICI) + ")"
        else:
            return pat
    return re.compile(pat.pattern.replace("{ALICI}", alici), pat.flags)


def evaluate_red_lines(
    clause_text: str,
    ct: ClauseType,
    scope_text: str | None = None,
    include_absence: bool = True,
    alici: str | None = None,
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
            for ham in rl.patterns:
                pat = _uygula_alici(ham, alici)
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
            if not any(_uygula_alici(p, alici).search(hay_scope)
                       for p in rl.absent_patterns):
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


def find_ambiguous(clause_text: str, kod: str | None = None) -> list[tuple[str, int, int, str]]:
    """(ifade, start, end, tur) - olculemez ifade gecisleri.

    tur: "zayiflatici" | "sure". Sure ifadeleri yalnizca sureye bagli madde
    tiplerinde dondurulur; aksi halde gurultu uretirler.

    Iki tur: once birebir, sonra aksansiz. Bazi sozlesmeler Turkce karakter
    kullanmadan yazilir ("makul bir sure"); bunlar da yakalanmalidir.
    """
    sure_onemli = kod is None or kod in SURE_HASSAS_KODLAR
    aranacak = list(ZAYIFLATICI) + (list(BELIRSIZ_SURE) if sure_onemli else [])

    hay = fold(clause_text)
    hay_flat = deaccent(clause_text)
    found: list[tuple[str, int, int, str]] = []
    seen: set[str] = set()
    for phrase in aranacak:
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
        tur = "sure" if phrase in BELIRSIZ_SURE else "zayiflatici"
        found.append((phrase, s, e, tur))
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


# --------------------------------------------------------------------------- #
# Taslak kusurlari — sozlesmenin KENDI yazim hatalari.
# Bunlar risk maddesi degil, imzalanmaya hazir olmayan metin isaretleridir.
# Gercek vaka: "vergilerin tamamı tarafından ödenerek" cumlesinde OZNE YOK;
# damga vergisini kimin odeyecegi sozlesmede hic yazmiyor.
# --------------------------------------------------------------------------- #

# "tamamı tarafından" gibi: iyelik ekli isim + tarafından, arada taraf adı yok.
_EKSIK_OZNE = re.compile(
    r"\b(tamamı|tümü|yarısı|bedeli|tutarı|masrafı|masrafları|ücreti|giderleri)"
    r"\s+tarafından\b",
    re.IGNORECASE,
)

# Doldurulmamis sablon bosluklari: "…………", "______", "..........."
# Noktalar ARADA BOSLUK OLMADAN ardisik olmali; aksi halde adres satirlarindaki
# ("No:5 ... Vergi Dairesi") dagini noktalar yanlis eslesiyordu.
_BOS_ALAN = re.compile(r"\u2026{2,}|_{5,}|\.{6,}")


def taslak_kusurlari(text: str) -> list[dict]:
    out: list[dict] = []

    for m in _EKSIK_OZNE.finditer(text):
        s, e = _expand_to_sentence(text, m.start(), m.end())
        out.append({
            "severity": "YUKSEK",
            "title": f"Cümlede özne eksik: \"{m.group(1)} tarafından\" — kimin yükümlü "
                     "olduğu yazılmamış",
            "rationale": (
                "Bu cümlede yükümlülüğün kime ait olduğu belirtilmemiş; taraf adı "
                "yazılmadan bırakılmış. Sözleşme bu hâliyle imzalanırsa masrafın "
                "veya edimin hangi tarafa ait olduğu tartışmalı hâle gelir."
            ),
            "quote": text[s:e].strip(),
        })

    # Bosluklar: alintiyi CUMLEYE degil, esslesmenin cevresine gore al.
    # Taraflar maddesinde nokta az oldugu icin cumle genisletmesi adres metnine
    # kaciyor ve alinti yaniltici goruunuyordu.
    bloklar: list[list[int]] = []
    for m in _BOS_ALAN.finditer(text):
        if bloklar and m.start() - bloklar[-1][1] < 240:
            bloklar[-1][1] = m.end()          # yakin bosluklar tek bulgu
        else:
            bloklar.append([m.start(), m.end()])

    for bas, son in bloklar:
        s0 = max(0, bas - 70)
        e0 = min(len(text), son + 70)
        alinti = " ".join(text[s0:e0].split())
        out.append({
            "severity": "ORTA",
            "title": "Sözleşmede doldurulmamış boşluk var",
            "rationale": (
                "Şablondan gelen boşluk doldurulmamış. İmza öncesinde bu alanların "
                "tamamlandığı teyit edilmelidir; boş bırakılan bir alan sonradan "
                "tek taraflı doldurulabilir."
            ),
            "quote": ("…" + alinti + "…")[:300],
        })

    return out[:12]      # rapor bu kusurlarla dolmasin
