"""Calisma zamani ayarlari — kullanicinin arayuzden girdigi model bilgileri.

Ortam degiskenleri varsayilani belirler; arayuzden girilen ayar onu EZER.
Dosya kalici birimde (/data) tutulur, boylece konteyner yeniden baslasa da kalir.

GUVENLIK NOTU: uygulamada kimlik dogrulama yok (bkz. docs/10 B1). Bu dosyaya
yazilan API anahtarini, uygulamaya erisebilen herkes degistirebilir ve
kullanabilir. Kapali agda / tek kullanicili kurulum icin tasarlandi.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import settings as env_settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: "RuntimeSettings | None" = None

SAGLAYICILAR = ("auto", "anthropic", "openai", "gemini", "custom", "heuristic")

# "custom" = OpenAI Chat Completions protokolunu konusan HERHANGI bir servis.
# Qwen, DeepSeek, Groq, OpenRouter, Together, yerel Ollama/vLLM... hepsi buraya girer.
VARSAYILAN_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "custom": "",
}

# Kullanicinin baslangic noktasi olarak kullanabilecegi bilinen uc noktalar.
HAZIR_UC_NOKTALAR = [
    {"ad": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "ornek_model": "deepseek-chat"},
    {"ad": "Qwen (DashScope)", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "ornek_model": "qwen-plus"},
    {"ad": "Groq", "base_url": "https://api.groq.com/openai/v1", "ornek_model": "llama-3.3-70b-versatile"},
    {"ad": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "ornek_model": "deepseek/deepseek-chat"},
    {"ad": "Together", "base_url": "https://api.together.xyz/v1", "ornek_model": "Qwen/Qwen2.5-72B-Instruct-Turbo"},
    {"ad": "Ollama (yerel)", "base_url": "http://localhost:11434/v1", "ornek_model": "qwen2.5:14b"},
    {"ad": "vLLM (yerel)", "base_url": "http://localhost:8000/v1", "ornek_model": "(sunucudaki model adı)"},
]

# Model adlarini tek tek saymak yerine SEVIYE sunuyoruz; saglayicilar model
# isimlerini sik degistirir. "-latest" takma adlari surum emekliliginden korur.
MODEL_SECENEKLERI = {
    "anthropic": [
        {"id": "claude-haiku-4-5", "label": "Hızlı ve ekonomik", "note": "toplu tarama"},
        {"id": "claude-sonnet-5", "label": "Dengeli", "note": ""},
        {"id": "claude-opus-5", "label": "En yetenekli", "note": "önerilen"},
    ],
    "openai": [
        {"id": "gpt-4o-mini", "label": "Hızlı ve ekonomik", "note": "toplu tarama"},
        {"id": "gpt-4.1", "label": "Dengeli", "note": ""},
        {"id": "gpt-5", "label": "En yetenekli", "note": "önerilen"},
    ],
    "custom": [],
    "gemini": [
        {"id": "gemini-flash-lite-latest", "label": "Hızlı ve ekonomik", "note": "toplu tarama"},
        {"id": "gemini-flash-latest", "label": "Dengeli", "note": "önerilen"},
        {"id": "gemini-2.5-pro", "label": "En yetenekli", "note": "yavaş, pahalı"},
    ],
}


@dataclass
class RuntimeSettings:
    provider: str = ""      # bos = ortam degiskenine birak
    api_key: str = ""
    model: str = ""
    base_url: str = ""      # yalnizca openai/custom icin
    # 1M token basina USD. 0 = kullanici girmedi -> yerlesik tablo denenir.
    # Kullanici girerse tablo EZILIR: fiyatlar degisirse biz guncellemesek de
    # kullanici kendi rakamini yazabilsin.
    price_in: float = 0.0
    price_out: float = 0.0
    updated_at: str = ""

    def masked_key(self) -> str:
        k = self.api_key or ""
        if not k:
            return ""
        if len(k) <= 10:
            return "•" * len(k)
        return f"{k[:4]}{'•' * 6}{k[-4:]}"


def _yol() -> Path:
    return env_settings.storage_dir / "settings.json"


def load() -> RuntimeSettings:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        p = _yol()
        if p.exists():
            try:
                _cache = RuntimeSettings(**json.loads(p.read_text(encoding="utf-8")))
            except Exception as exc:
                log.warning("Ayar dosyası okunamadı (%s); varsayılanlar kullanılıyor", exc)
                _cache = RuntimeSettings()
        else:
            _cache = RuntimeSettings()
        return _cache


def save(**alanlar) -> RuntimeSettings:
    global _cache
    with _lock:
        mevcut = _cache or RuntimeSettings()
        for k, v in alanlar.items():
            if v is not None and hasattr(mevcut, k):
                setattr(mevcut, k, v)
        mevcut.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        p = _yol()
        p.parent.mkdir(parents=True, exist_ok=True)
        gecici = p.with_suffix(".tmp")
        gecici.write_text(json.dumps(asdict(mevcut), ensure_ascii=False, indent=2),
                          encoding="utf-8")
        try:
            os.chmod(gecici, 0o600)     # anahtar dosyasi yalnizca sahibine acik
        except OSError:
            pass
        gecici.replace(p)
        _cache = mevcut
        return mevcut


def clear_key() -> RuntimeSettings:
    return save(api_key="")


# --------------------------------------------------------------------------- #
# Son model hatasi — arayuz kullaniciya "anahtarin bitmis, ne yapmak istersin?"
# diyebilsin diye tutulur. Bellekte; surec yeniden baslayinca sifirlanir.
# --------------------------------------------------------------------------- #
_son_hata: dict | None = None


_HATA_OZETI = {
    "auth": "API anahtarı geçersiz veya yetkisiz",
    "quota": "Kota veya hız sınırı aşıldı",
    "model": "Model bulunamadı ya da bu hesaba kapalı",
    "other": "Sağlayıcı hatası",
}


def _sadelestir(mesaj: str, tur: str) -> str:
    """Ham API gövdesini kullaniciya gosterilecek tek satira indirger.

    Saglayicilar coğu zaman JSON gövdesi doner; arayuze o gövde dusmemeli.
    """
    import re as _re

    m = _re.search(r'"message"\s*:\s*"([^"]{5,200})"', mesaj or "")
    ayrinti = m.group(1) if m else (mesaj or "").split("\n")[0]
    kod = _re.search(r"HTTP (\d{3})", mesaj or "")
    onek = f"HTTP {kod.group(1)} · " if kod else ""
    return f"{onek}{_HATA_OZETI.get(tur, '')}: {ayrinti}"[:280]


def hata_kaydet(tur: str, mesaj: str, model: str = "", saglayici: str = "") -> None:
    global _son_hata
    with _lock:
        _son_hata = {
            "kind": tur,             # auth | quota | model | other
            "message": _sadelestir(mesaj, tur),
            "raw": (mesaj or "")[:400],
            "model": model,
            "provider": saglayici,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def son_hata() -> dict | None:
    return _son_hata


def hata_temizle() -> None:
    global _son_hata
    with _lock:
        _son_hata = None


def hata_turu(mesaj: str) -> str:
    m = (mesaj or "").lower()
    # Kota once bakilir: bazi saglayicilar (Qwen'in maas ucu) biten kotayi 403
    # ile dondurur. Once 401/403'e bakilirsa kullaniciya "anahtarin gecersiz"
    # denir ve anahtarini bosuna degistirir.
    if ("quota" in m or "exhausted" in m or "429" in m or "rate limit" in m
            or "kota" in m or "insufficient" in m or "billing" in m):
        return "quota"
    if "401" in m or "403" in m or "invalid" in m or "authentication" in m or "api key" in m:
        return "auth"
    if "404" in m or "not found" in m or "no longer available" in m:
        return "model"
    return "other"


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# --------------------------------------------------------------------------- #
def etkin_saglayici() -> str:
    """Arayuz ayari > ortam degiskeni."""
    r = load()
    return r.provider or env_settings.llm_provider


def etkin_anahtar(saglayici: str) -> str:
    r = load()
    if r.api_key and (not r.provider or r.provider == saglayici or r.provider == "auto"):
        return r.api_key
    if saglayici == "gemini":
        return env_settings.google_api_key
    if saglayici == "anthropic":
        return env_settings.anthropic_api_key
    if saglayici in ("openai", "custom"):
        return env_settings.openai_api_key
    return ""


def etkin_model(saglayici: str) -> str:
    r = load()
    if r.model:
        return r.model
    if saglayici == "gemini":
        return env_settings.model_gemini
    if saglayici == "anthropic":
        return env_settings.model_main
    if saglayici == "openai":
        return env_settings.model_openai
    return env_settings.model_custom       # custom: varsayilan yok, kullanici girer


def etkin_fiyat() -> tuple[float, float] | None:
    """Kullanicinin girdigi 1M token fiyatlari. Ikisi de 0 ise None."""
    r = load()
    if r.price_in or r.price_out:
        return (float(r.price_in or 0), float(r.price_out or 0))
    return None


def etkin_base_url(saglayici: str) -> str:
    r = load()
    if r.base_url:
        return r.base_url
    if saglayici == "openai":
        return env_settings.openai_base_url or VARSAYILAN_BASE_URL["openai"]
    if saglayici == "custom":
        return env_settings.custom_base_url
    return ""


def anahtar_kaynagi(saglayici: str) -> str:
    r = load()
    if r.api_key:
        return "ui"
    if saglayici == "gemini" and env_settings.google_api_key:
        return "env"
    if saglayici == "anthropic" and env_settings.anthropic_api_key:
        return "env"
    if saglayici in ("openai", "custom") and env_settings.openai_api_key:
        return "env"
    return "none"
