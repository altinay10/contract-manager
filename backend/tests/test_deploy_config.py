"""Dagitim yapilandirmasi tutarliligi.

Gercek hata: docker-compose.yml bazi degiskenleri sabit yaziyordu
(`LLM_TIMEOUT_SECONDS: "90"`). .env dosyasinda ayni anahtar 120 olarak
tanimliydi ama konteynere hic ulasmiyordu — ayar sessizce yok sayiliyordu ve
sebebi hicbir yerde gorunmuyordu. Bu test o sinif hatayi bir daha birakmaz.
"""
from __future__ import annotations

import re
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent.parent
COMPOSE = KOK / "docker-compose.yml"
ORNEK_ENV = KOK / ".env.example"
DOCKERFILE = KOK / "backend" / "Dockerfile"


def _compose_ortam_degiskenleri() -> dict[str, str]:
    """compose'un `environment:` blogundaki ANAHTAR: "deger" ciftleri."""
    satirlar = COMPOSE.read_text(encoding="utf-8").splitlines()
    icinde = False
    bulunan: dict[str, str] = {}
    for satir in satirlar:
        if re.match(r"^\s{4}environment:\s*$", satir):
            icinde = True
            continue
        if icinde:
            # Blok, daha az girintili bir anahtarla biter.
            if satir.strip() and not satir.startswith(" " * 6):
                break
            m = re.match(r'^\s{6}([A-Z_][A-Z0-9_]*):\s*"(.*)"\s*$', satir)
            if m:
                bulunan[m.group(1)] = m.group(2)
    return bulunan


def _ornek_env_anahtarlari() -> set[str]:
    anahtarlar = set()
    for satir in ORNEK_ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", satir.strip())
        if m:
            anahtarlar.add(m.group(1))
    return anahtarlar


def test_compose_env_degerlerini_sabitlemez():
    ortam = _compose_ortam_degiskenleri()
    assert ortam, "compose environment blogu okunamadi - test kaliplari eskimis olabilir"

    ayarlanabilir = _ornek_env_anahtarlari()
    sabitlenmis = [
        f"{k}={v!r}"
        for k, v in ortam.items()
        if k in ayarlanabilir and "${" not in v
    ]
    assert not sabitlenmis, (
        ".env.example'da tanimli olmasina ragmen compose'da sabit yazilmis "
        "degiskenler var; .env'e yazilan degerler sessizce yok sayilir: "
        + ", ".join(sorted(sabitlenmis))
    )


def test_swagger_bayragi_dagitimda_kapali():
    """Acik aga konulan kurulumda /docs ve /openapi.json disari acilmamali."""
    ortam = _compose_ortam_degiskenleri()
    assert "EXPOSE_DOCS" in ortam, "compose EXPOSE_DOCS'u gecirmiyor"
    assert ortam["EXPOSE_DOCS"] == "${EXPOSE_DOCS:-0}", (
        f"EXPOSE_DOCS varsayilani kapali degil: {ortam['EXPOSE_DOCS']}"
    )


def test_compose_uretim_asamasini_hedefler():
    """Dockerfile cok asamali: hedef verilmezse Docker EN SON asamayi uretir.

    Son asama `test` — pytest ve test paketlerini kurar. `target: runtime`
    dusurulurse uretim imajina test bagimliliklari girer ve imaj buyur.
    """
    metin = COMPOSE.read_text(encoding="utf-8")
    assert "target: runtime" in metin, (
        "compose build hedefi yok; uretim imajina test asamasi girer"
    )


def test_dockerfile_test_asamasi_uretimden_ayri():
    """pytest yalnizca test asamasinda kurulmali."""
    if not DOCKERFILE.exists():          # test konteynerinde Dockerfile yok
        import pytest
        pytest.skip("Dockerfile bu baglamda yok")
    metin = DOCKERFILE.read_text(encoding="utf-8")
    assert "AS runtime" in metin, "uretim asamasi adlandirilmamis"
    assert "FROM runtime AS test" in metin, "ayri test asamasi yok"
    uretim, _, test_asamasi = metin.partition("FROM runtime AS test")
    assert "requirements-dev" not in uretim, (
        "test bagimliliklari uretim asamasinda kuruluyor"
    )
    assert "requirements-dev" in test_asamasi
