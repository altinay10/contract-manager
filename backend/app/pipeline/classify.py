"""Asama 6: Madde siniflandirma.

Hibrit: anahtar kelime skoru aday listesini uretir; model varsa adaylari teyit eder.
Modele bos sayfa yerine kisitli bir aday listesi vermek (K2 daraltmasi) halusinasyonu
ve maliyeti birlikte dusurur.

TURKCE ESLESTIRME NOTU
----------------------
Duz alt-dizgi aramasi bu dilde iki yonden bozulur:
  1. Ek yuzunden KACIRIR : "veri merkezi" anahtari "veri merkezlerinde" ile eslesmez.
  2. Kelime icinde YAKALAR: "telif" anahtari "muhtelif" kelimesinin icinde eslesir.
Bu yuzden her anahtar kelime; sonundaki cekim eki budanip, basina kelime siniri
konularak bir desene cevrilir.
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..playbook.loader import ClauseType, load_playbook
from ..textutil import fold, tr_lower

HEADING_WEIGHT = 3.0
BODY_WEIGHT = 1.0
# Cok kelimeli anahtar ("veri merkezi") tek kelimeliden ("bildirim") cok daha guclu
# bir sinyaldir; esik, tek bir genel kelimenin yetmeyecegi sekilde secildi.
OZGULLUK = 0.5
MIN_SCORE = 1.5
MAX_CANDIDATES = 4

TR_HARF = "a-zçğıöşü"

# Uzundan kisaya: ilk eslesen ek budanir.
_SUFFIXES = (
    # fiilden turemis isim ekleri: "saklama" -> "sakla" (boylece "saklanmasi" da eslesir)
    "mesi", "ması", "mek", "mak", "me", "ma",
    "larinin", "lerinin", "larında", "lerinde", "larindan", "lerinden",
    "ları", "leri", "lar", "ler",
    "sının", "sinin", "sunun", "sünün",
    "nın", "nin", "nun", "nün",
    "ında", "inde", "unda", "ünde",
    "ının", "inin", "unun", "ünün",
    "dan", "den", "tan", "ten",
    "sı", "si", "su", "sü",
    "ın", "in", "un", "ün",
    "da", "de", "ta", "te",
    "ı", "i", "u", "ü",
)
_MIN_STEM = 5

# Turkce unsuz yumusamasi: kelimeye ek geldiginde son sessiz degisir.
#   sorumluluk -> sorumluluğu,  kitap -> kitabı,  agac -> agaci
# Anahtar kelime govdesinin son harfi bu yuzden bir karakter sinifina cevrilir.
_MUTATION = {"k": "[kğ]", "p": "[pb]", "ç": "[çc]", "t": "[td]", "g": "[gğ]"}


def _stem(word: str) -> str:
    """Son kelimeden TEK bir cekim eki budar; govde cok kisalirsa dokunmaz."""
    for ek in _SUFFIXES:
        if word.endswith(ek):
            govde = word[: -len(ek)]
            if len(govde) >= _MIN_STEM:
                return govde
            break
    return word


@lru_cache(maxsize=2048)
def keyword_pattern(kw: str) -> re.Pattern:
    """Anahtar kelimeyi ek-toleransli, kelime sinirli bir desene cevirir."""
    parcalar = fold(kw).split()
    if not parcalar:
        return re.compile(r"(?!x)x")  # hicbir seyle eslesmez
    # Cok kelimeli anahtarda HER kelime ek alabilir:
    # "hizmeti gelistirmek" anahtari "hizmetlerini gelistirmek" ile eslesmelidir.
    parcalar = [_stem(w) for w in parcalar]
    desenler = []
    for i, w in enumerate(parcalar):
        if w and w[-1] in _MUTATION:
            govde = re.escape(w[:-1]) + _MUTATION[w[-1]]
        else:
            govde = re.escape(w)
        son_kelime = i == len(parcalar) - 1
        # Ara kelimelerde ek serbest, son kelimede de serbest.
        desenler.append(govde + f"[{TR_HARF}]*")
    govde = r"\s+".join(desenler)
    # Basta kelime siniri kelime ICINDE yakalamayi engeller ("telif" != "muhtelif").
    return re.compile(rf"(?<![{TR_HARF}0-9]){govde}", re.IGNORECASE)


def _hits(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text))


def score_clause(heading: str, text: str, contract_type: str) -> list[tuple[str, float]]:
    """(code, skor) listesi, azalan sirada."""
    pb = load_playbook()
    fh = fold(heading)
    ft = fold(text)
    out: list[tuple[str, float]] = []

    for ct in pb.values():
        if not ct.applies(contract_type):
            continue
        score = 0.0
        for kw in ct.keywords:
            pat = keyword_pattern(kw)
            ozgulluk = 1.0 + OZGULLUK * kw.count(" ")
            if pat.search(fh):
                score += HEADING_WEIGHT * ozgulluk
            n = _hits(pat, ft)
            if n:
                score += BODY_WEIGHT * min(n, 3) * ozgulluk
        # Kirmizi cizgi deseni eslesiyorsa bu, anahtar kelimeden cok daha guclu
        # bir sinyaldir: madde tipi kesin atanir. Aksi halde siniflandirma kacagi
        # "bu koruma sozlesmede yok" seklinde yanlis bir beyana donusur.
        if score < MIN_SCORE and _desen_isabeti(text, ct):
            score = max(score, MIN_SCORE + 1.0)

        if score >= MIN_SCORE:
            out.append((ct.code, round(score, 2)))

    out.sort(key=lambda x: -x[1])
    return out[:MAX_CANDIDATES]


def _desen_isabeti(text: str, ct: ClauseType) -> bool:
    """Bu madde tipinin kirmizi cizgi desenlerinden biri metinde eslesiyor mu?"""
    hay = tr_lower(text)
    for rl in ct.red_lines:
        for pat in rl.patterns:          # yalnizca POZITIF desenler; yokluk kurallari degil
            if pat.search(hay):
                return True
    return False


def classify(heading: str, text: str, contract_type: str) -> list[dict]:
    raw = score_clause(heading, text, contract_type)
    if not raw:
        return []
    top = raw[0][1]
    picked = []
    for code, score in raw:
        # Ana adaya gore cok zayif kalanlar elenir.
        if score < max(MIN_SCORE, top * 0.35):
            continue
        picked.append(
            {
                "code": code,
                "confidence": round(min(0.99, 0.45 + 0.5 * (score / max(top, 1e-6))), 2),
                "method": "KEYWORD",
            }
        )
    return picked


def types_for(codes: list[dict]) -> list[ClauseType]:
    pb = load_playbook()
    return [pb[c["code"]] for c in codes if c["code"] in pb]
