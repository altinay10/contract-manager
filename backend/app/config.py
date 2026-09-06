"""Uygulama yapılandırması. 12-factor: her şey ortam değişkeninden okunur."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class Settings:
    # --- depolama ---
    storage_dir: Path = Path(_env("STORAGE_DIR", str(BASE_DIR / "storage")))
    database_url: str = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'storage' / 'app.db'}")

    # --- playbook ---
    playbook_dir: Path = Path(_env("PLAYBOOK_DIR", str(BASE_DIR / "playbook")))

    # --- model ---
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")
    model_main: str = _env("MODEL_MAIN", "claude-opus-5")
    model_cheap: str = _env("MODEL_CHEAP", "claude-haiku-4-5")
    google_api_key: str = _env("GOOGLE_API_KEY", "") or _env("GEMINI_API_KEY", "")
    model_gemini: str = _env("MODEL_GEMINI", "gemini-flash-latest")
    model_gemini_cheap: str = _env("MODEL_GEMINI_CHEAP", "gemini-flash-lite-latest")
    openai_api_key: str = _env("OPENAI_API_KEY", "")
    openai_base_url: str = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_openai: str = _env("MODEL_OPENAI", "gpt-4.1")
    # "custom": OpenAI uyumlu herhangi bir uç (Qwen, DeepSeek, Groq, Ollama...)
    custom_base_url: str = _env("CUSTOM_BASE_URL", "")
    model_custom: str = _env("MODEL_CUSTOM", "")
    # auto | anthropic | openai | gemini | custom | heuristic
    llm_provider: str = _env("LLM_PROVIDER", "auto")

    # --- dayanıklılık (failsafe) ---
    stage_max_attempts: int = _env_int("STAGE_MAX_ATTEMPTS", 3)
    item_max_attempts: int = _env_int("ITEM_MAX_ATTEMPTS", 2)
    retry_base_seconds: float = float(_env("RETRY_BASE_SECONDS", "1.5"))
    heartbeat_seconds: int = _env_int("HEARTBEAT_SECONDS", 15)
    orphan_after_seconds: int = _env_int("ORPHAN_AFTER_SECONDS", 90)
    # Periyodik öksüz tarayıcı. Testlerde ve tek seferlik CLI koşularında kapatılır.
    sweeper_enabled: bool = _env("SWEEPER_ENABLED", "1") not in ("0", "false", "False")

    # --- model butce tavanlari (takilma/kacak korumasi) ---
    # Bu degerler asildiginda model cagrilari KAPATILIR; analiz kural katmaniyla
    # tamamlanir. Yeniden deneme yapilmaz.
    max_llm_calls: int = _env_int("MAX_LLM_CALLS", 80)
    max_cost_usd: float = float(_env("MAX_COST_USD", "1.00"))
    max_total_tokens: int = _env_int("MAX_TOTAL_TOKENS", 400_000)
    llm_deadline_seconds: int = _env_int("LLM_DEADLINE_SECONDS", 900)
    max_consecutive_failures: int = _env_int("MAX_CONSECUTIVE_FAILURES", 3)
    llm_timeout_seconds: int = _env_int("LLM_TIMEOUT_SECONDS", 90)
    # Gecici saglayici hatalari (503/429) icin sinirli yeniden deneme. Yeniden
    # deneme olmayinca tek bir 503 devre kesiciye hata yaziyor, ust uste ucu tum
    # analizi durduruyordu.
    # Kotasi biten model yerine sirayla denenecek yedekler (virgulle ayrilir).
    # Bos birakilirsa devir yok: kota bitince analiz kural katmaniyla surer.
    model_fallbacks: str = _env("MODEL_FALLBACKS", "")
    llm_retry_attempts: int = _env_int("LLM_RETRY_ATTEMPTS", 3)
    llm_retry_backoff_seconds: float = float(_env("LLM_RETRY_BACKOFF_SECONDS", "2"))
    # Modele gonderilecek azami madde sayisi (agirliga gore secilir). 0 = sinirsiz.
    max_llm_clauses: int = _env_int("MAX_LLM_CLAUSES", 40)
    # Coklu mercek ve karsi-gorus pahalidir; kapatilabilir.
    enable_lenses: bool = _env("ENABLE_LENSES", "1") not in ("0", "false", "False")
    enable_rebuttal: bool = _env("ENABLE_REBUTTAL", "1") not in ("0", "false", "False")

    # --- surum karsilastirma ---
    # Modele gonderilecek azami degisiklik sayisi. Fazlasi sablon aciklamayla
    # kalir; deterministik fark yine tam gosterilir. 0 = sinirsiz.
    max_compare_explain: int = _env_int("MAX_COMPARE_EXPLAIN", 30)
    # Gri bant: benzerligi bu araliktaki ciftler modele "ayni madde mi?" diye
    # sorulur. Ust sinir compare.SIM_THRESHOLD ile ayni olmali.
    compare_gray_low: float = float(_env("COMPARE_GRAY_LOW", "0.45"))
    # Ablasyon anahtarlari (docs/08 §7): her kaldirac tek tek olculebilsin.
    enable_compare_adjudicate: bool = _env("ENABLE_COMPARE_ADJUDICATE", "1") not in ("0", "false", "False")
    enable_compare_rebuttal: bool = _env("ENABLE_COMPARE_REBUTTAL", "1") not in ("0", "false", "False")

    # --- OCR (taranmış belgeler) ---
    ocr_enabled: bool = _env("OCR_ENABLED", "1") not in ("0", "false", "False")
    ocr_lang: str = _env("OCR_LANG", "tur+eng")
    ocr_dpi: int = _env_int("OCR_DPI", 300)
    ocr_max_pages: int = _env_int("OCR_MAX_PAGES", 60)
    tesseract_cmd: str = _env("TESSERACT_CMD", "tesseract")

    # --- kimlik doğrulama ---
    # AUTH_ENABLED=0 yalnızca yerel geliştirme ve testler içindir.
    auth_enabled: bool = _env("AUTH_ENABLED", "1") not in ("0", "false", "False")
    app_password: str = _env("APP_PASSWORD", "")
    session_secret: str = _env("SESSION_SECRET", "")
    session_hours: int = _env_int("SESSION_HOURS", 12)
    cookie_secure: bool = _env("COOKIE_SECURE", "0") not in ("0", "false", "False")

    # --- limitler ---
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 40)
    llm_concurrency: int = _env_int("LLM_CONCURRENCY", 4)

    def ensure_dirs(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "reports").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
