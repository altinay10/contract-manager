"""Eşleştirme ve fark çıkarma.

İki sürümün birimleri eşleştirilir, eşleşenlerde kelime bazında fark alınır.

**Bilinçli yanlılık: şüphede kalırsan eşleştirme.** İki hata simetrik değil:

* *Eşleştirmedi ama eşleşmeliydi* → "silindi" ve "eklendi" diye iki kart
  çıkar. Göz yorar; bilgi tamdır.
* *Eşleştirdi ama eşleşmemeliydi* → alakasız iki madde yan yana konur, kelime
  farkı gürültüden ibaret olur ve okuyan kişi anlamsız kartı atlar. Asıl
  tehlike budur.

Bu yüzden eşikler yüksek tutulur. Aynı madde numarasını taşımak bile tek
başına yeterli değildir: numara aynı ama metin tamamen farklıysa (araya madde
girip numaralar kaydığında olur) eşleşme kabul edilmez.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..textutil import fold
from .coverage import Unit

# Benzerlik eşiği — bunun altındaki çiftler eşleştirilmez, silindi+eklendi olur.
SIM_THRESHOLD = 0.72
# Numara eşleşmesinin geçerli sayılması için gereken asgari metin benzerliği.
# Bu olmadan, araya madde girip numaralar kaydığında alakasız maddeler eşleşir.
NUMBER_MATCH_MIN_SIM = 0.35
# Bunun üstünde ve numara değişmişse: taşınmış/yeniden numaralanmış sayılır.
MOVED_MIN_SIM = 0.95
# Gri bant alt sınırı. Bu aralıktaki çiftler algoritmaya göre "kararsız"dır:
# eşleştirmeye yetecek kadar benzer değil, ama yok saymaya da fazla benzer.
# Hakem verilmezse eşleştirilmezler — yani bugünkü davranış korunur.
GRAY_LOW = 0.45
# Hakeme sorulacak azami çift sayısı; maliyet tavanı.
MAX_ADJUDICATE = 12

_WORD = re.compile(r"\S+\s*")
_ANLAMLI = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+")


@dataclass
class Change:
    change_type: str                       # EKLENDI/SILINDI/DEGISTI/TASINDI/AYNI
    old: Unit | None = None
    new: Unit | None = None
    similarity: float = 0.0
    word_diff: list[dict] = field(default_factory=list)
    significant: bool = True
    order_index: int = 0
    # Bu eşleşmeyi hakem geçişi mi kurdu? (gri banttan kurtarılmış çift)
    adjudicated: bool = False

    @property
    def is_gap_unit(self) -> bool:
        u = self.new or self.old
        return bool(u and u.is_gap)


def _tokens(text: str) -> list[str]:
    """Boşluğu koruyan kelime dizisi — fark segmentleri yeniden birleştirilebilsin."""
    return _WORD.findall(text)


def _key(text: str) -> list[str]:
    """Benzerlik karşılaştırması için sadeleştirilmiş anahtar.

    Büyük/küçük harf, aksan ve noktalama farkları benzerliği bulandırmasın.
    """
    return _ANLAMLI.findall(fold(text))


def similarity(a: str, b: str) -> float:
    ka, kb = _key(a), _key(b)
    if not ka and not kb:
        return 1.0
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


def word_diff(old: str, new: str) -> list[dict]:
    """Kelime bazında fark: [{op, text}] — op: equal | delete | insert."""
    a, b = _tokens(old), _tokens(new)
    out: list[dict] = []

    def ekle(op: str, parca: list[str]) -> None:
        if not parca:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += "".join(parca)
        else:
            out.append({"op": op, "text": "".join(parca)})

    for op, i1, i2, j1, j2 in SequenceMatcher(None, [fold(w) for w in a],
                                              [fold(w) for w in b]).get_opcodes():
        if op == "equal":
            ekle("equal", a[i1:i2])
        elif op == "delete":
            ekle("delete", a[i1:i2])
        elif op == "insert":
            ekle("insert", b[j1:j2])
        else:                                  # replace
            ekle("delete", a[i1:i2])
            ekle("insert", b[j1:j2])
    return out


def _anlamli_fark_var(diff: list[dict]) -> bool:
    """Fark yalnız boşluk/noktalama mı, yoksa gerçek kelime değişikliği mi?"""
    for p in diff:
        if p["op"] in ("delete", "insert") and _ANLAMLI.search(p["text"]):
            return True
    return False


def _tasima_govdesi(u: Unit) -> str:
    """Taşınma kontrolü için başlık satırını (numarayı taşıyan satırı) çıkarır.

    "MADDE 3 - GİZLİLİK" ile "MADDE 4 - GİZLİLİK" arasındaki tek fark
    numaranın kendisidir; gövde aynıysa bu bir taşınmadır, değişiklik değil.
    Numarayı hesaba katarsak kısa maddelerde oran eşiğin altına düşer ve
    taşınma yanlışlıkla "değişti" görünür.
    """
    if u.is_gap or not u.number:
        return u.text
    ilk, _, kalan = u.text.partition("\n")
    return kalan if (u.number in ilk and kalan.strip()) else u.text


def _numara_eslesmeleri(old: list[Unit], new: list[Unit]) -> list[tuple[int, int]]:
    """İki tarafta da TEKİL olan madde numaralarını eşle."""
    def tekil(units: list[Unit]) -> dict[str, int]:
        sayac: dict[str, list[int]] = {}
        for i, u in enumerate(units):
            no = u.number.strip()
            if no:
                sayac.setdefault(no, []).append(i)
        return {no: idx[0] for no, idx in sayac.items() if len(idx) == 1}

    eski, yeni = tekil(old), tekil(new)
    ciftler = []
    for no, i in eski.items():
        j = yeni.get(no)
        if j is None:
            continue
        # Numara aynı diye yetinme: metin de tutmalı. Aksi hâlde araya madde
        # girip numaralar kaydığında alakasız maddeler eşleşir.
        if similarity(old[i].text, new[j].text) >= NUMBER_MATCH_MIN_SIM:
            ciftler.append((i, j))
    return ciftler


def _benzerlik_eslesmeleri(old: list[Unit], new: list[Unit],
                           eski_bos: set[int], yeni_bos: set[int]) -> list[tuple[int, int]]:
    """Kalanlar için en iyi karşılıklı eşleşmeler; eşiğin altı eşleşmez."""
    adaylar = []
    for i in sorted(eski_bos):
        for j in sorted(yeni_bos):
            s = similarity(old[i].text, new[j].text)
            if s >= SIM_THRESHOLD:
                adaylar.append((s, i, j))
    adaylar.sort(key=lambda t: (-t[0], t[1], t[2]))

    ciftler, kullanilan_i, kullanilan_j = [], set(), set()
    for s, i, j in adaylar:
        if i in kullanilan_i or j in kullanilan_j:
            continue
        ciftler.append((i, j))
        kullanilan_i.add(i)
        kullanilan_j.add(j)
    return ciftler


def _hakem_eslesmeleri(old: list[Unit], new: list[Unit],
                       eski_bos: set[int], yeni_bos: set[int],
                       adjudicator) -> list[tuple[int, int]]:
    """Gri banttaki çiftleri hakeme sorar.

    Hakem ne derse desin KAPSAMA BOZULMAZ: eşleşme kurulmazsa iki birim de
    "silindi" ve "eklendi" olarak ayrı ayrı görünür. Hakem yalnızca iki kartı
    tek karta birleştirebilir; bir birimi ortadan kaldıramaz.
    """
    adaylar = []
    for i in sorted(eski_bos):
        en_iyi = None
        for j in sorted(yeni_bos):
            s = similarity(old[i].text, new[j].text)
            if GRAY_LOW <= s < SIM_THRESHOLD and (en_iyi is None or s > en_iyi[0]):
                en_iyi = (s, j)
        if en_iyi is not None:
            adaylar.append((en_iyi[0], i, en_iyi[1]))
    adaylar.sort(key=lambda t: (-t[0], t[1], t[2]))

    ciftler, kullanilan_i, kullanilan_j = [], set(), set()
    for s, i, j in adaylar[:MAX_ADJUDICATE]:
        if i in kullanilan_i or j in kullanilan_j:
            continue
        try:
            ayni = adjudicator(old[i], new[j], s)
        except Exception:
            # Hakem çökerse eşleştirme yapılmaz — güvenli yön budur.
            continue
        if ayni:
            ciftler.append((i, j))
            kullanilan_i.add(i)
            kullanilan_j.add(j)
    return ciftler


def align(old: list[Unit], new: list[Unit], adjudicator=None) -> list[Change]:
    """İki sürümün birimlerini eşleştirip değişiklik listesi üretir.

    Her eski birim ve her yeni birim çıktıda TAM OLARAK BİR kez görünür.
    Bu, karşılaştırmanın hiçbir şeyi atlamadığının garantisidir.
    """
    ciftler = _numara_eslesmeleri(old, new)
    eski_bos = set(range(len(old))) - {i for i, _ in ciftler}
    yeni_bos = set(range(len(new))) - {j for _, j in ciftler}
    ciftler += _benzerlik_eslesmeleri(old, new, eski_bos, yeni_bos)

    # Hakem geçişi: kalan gri bant çiftleri modele sorulur. Hakem verilmezse
    # bu adım atlanır ve algoritma tamamen deterministik kalır.
    hakem_ciftleri: set[tuple[int, int]] = set()
    if adjudicator is not None:
        eski_bos = set(range(len(old))) - {i for i, _ in ciftler}
        yeni_bos = set(range(len(new))) - {j for _, j in ciftler}
        yeni_ciftler = _hakem_eslesmeleri(old, new, eski_bos, yeni_bos, adjudicator)
        hakem_ciftleri = set(yeni_ciftler)
        ciftler += yeni_ciftler

    eslesen_i = {i for i, _ in ciftler}
    eslesen_j = {j for _, j in ciftler}

    degisiklikler: list[tuple[float, Change]] = []

    for i, j in ciftler:
        eu, nu = old[i], new[j]
        s = similarity(eu.text, nu.text)
        d = word_diff(eu.text, nu.text)
        anlamli = _anlamli_fark_var(d)
        if not anlamli:
            tur = "AYNI"
        elif (eu.number.strip() != nu.number.strip()
                and similarity(_tasima_govdesi(eu), _tasima_govdesi(nu)) >= MOVED_MIN_SIM):
            tur = "TASINDI"
        else:
            tur = "DEGISTI"
        degisiklikler.append((float(j), Change(
            change_type=tur, old=eu, new=nu, similarity=s,
            word_diff=d if tur != "AYNI" else [], significant=anlamli,
            adjudicated=(i, j) in hakem_ciftleri,
        )))

    # Eşleşmeyen yeni birimler: eklendi
    for j in sorted(yeni_bos - eslesen_j):
        nu = new[j]
        degisiklikler.append((float(j), Change(
            change_type="EKLENDI", new=nu, similarity=0.0,
            word_diff=[{"op": "insert", "text": nu.text}],
            significant=bool(_ANLAMLI.search(nu.text)),
        )))

    # Eşleşmeyen eski birimler: silindi. Yeni sürümdeki yerlerini,
    # kendilerinden önce gelen son eşleşmenin konumundan tahmin ederiz.
    onceki_j: dict[int, float] = {}
    son = -0.5
    for i in range(len(old)):
        eslesme = next((j for a, j in ciftler if a == i), None)
        if eslesme is not None:
            son = float(eslesme)
        onceki_j[i] = son + 0.5
    for i in sorted(set(range(len(old))) - eslesen_i):
        eu = old[i]
        degisiklikler.append((onceki_j[i], Change(
            change_type="SILINDI", old=eu, similarity=0.0,
            word_diff=[{"op": "delete", "text": eu.text}],
            significant=bool(_ANLAMLI.search(eu.text)),
        )))

    degisiklikler.sort(key=lambda t: t[0])
    out = []
    for k, (_, c) in enumerate(degisiklikler):
        c.order_index = k
        out.append(c)
    return out


def stats(changes: list[Change]) -> dict:
    s = {t: 0 for t in ("EKLENDI", "SILINDI", "DEGISTI", "TASINDI", "AYNI")}
    for c in changes:
        s[c.change_type] += 1
    s["toplam"] = len(changes)
    s["onemli"] = sum(1 for c in changes if c.significant and c.change_type != "AYNI")
    return s
