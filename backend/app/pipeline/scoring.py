"""Risk skorlamasi (docs/01 §5).

madde_bulgu_skoru = siddet x playbook_agirlik x baglam_carpani
sozlesme_skoru    = 100 - normalize(toplam)
Veto kurali: tek bir kirmizi cizgi ihlali varsa skor ne olursa olsun band KIRMIZI.
"""
from __future__ import annotations

from ..playbook.loader import load_playbook

SEVERITY_POINTS = {"KRITIK": 5.0, "YUKSEK": 3.0, "ORTA": 1.5, "DUSUK": 0.6, "BILGI": 0.0}


def context_multiplier(code: str, involves_personal_data: bool, is_outsourcing: bool) -> float:
    pb = load_playbook()
    ct = pb.get(code)
    mult = 1.0
    if not ct:
        return mult
    if involves_personal_data and ct.category == "VERI_GUVENLIK":
        mult *= 1.25
    if is_outsourcing and ct.category == "REGULASYON":
        mult *= 1.5
    return mult


def finding_score(code: str, severity: str, confidence: float,
                  involves_personal_data: bool, is_outsourcing: bool) -> float:
    pb = load_playbook()
    weight = pb[code].weight if code in pb else 3
    base = SEVERITY_POINTS.get(severity, 1.0) * weight
    base *= context_multiplier(code, involves_personal_data, is_outsourcing)
    # Dusuk guvenli bulgu skoru tam agirlikla ezmez.
    return round(base * max(0.4, min(1.0, confidence)), 2)


def contract_score(findings: list[dict], involves_personal_data: bool, is_outsourcing: bool):
    """(skor, band, veto_gerekce) doner."""
    total = 0.0
    red_lines = 0
    for f in findings:
        total += finding_score(
            f["code"], f["severity"], f.get("confidence", 0.8),
            involves_personal_data, is_outsourcing,
        )
        if f["finding_type"] == "RED_LINE" and f["severity"] in ("KRITIK", "YUKSEK"):
            red_lines += 1

    # Doyumlu egri: ceza arttikca skor duser ama sifira yapismaz. Boylece "kotu" ile
    # "cok kotu" sozlesme birbirinden ayirt edilebilir kalir.
    #   ceza  40 -> ~82,  100 -> ~64,  200 -> ~47,  360 -> ~33
    K = 180.0
    penalty = 100.0 * total / (total + K)
    score = round(max(0.0, 100.0 - penalty), 1)

    if score >= 80:
        band = "YESIL"
    elif score >= 60:
        band = "SARI"
    else:
        band = "KIRMIZI"

    veto = ""
    if red_lines:
        veto = (
            f"{red_lines} adet kırmızı çizgi ihlali tespit edildiği için skordan bağımsız "
            "olarak KIRMIZI işaretlendi."
        )
        band = "KIRMIZI"
    return score, band, veto


BAND_LABEL = {
    "YESIL": "Yeşil — imzalanabilir",
    "SARI": "Sarı — müzakere edilmeli",
    "KIRMIZI": "Kırmızı — mevcut hâliyle imzalanmamalı",
}
