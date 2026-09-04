"""LLM soyutlama katmani.

Tum model cagrilari bu arayuzun arkasindadir. Bugun Claude veya Gemini, yarin lokal
model - prompt ve sema degismez, yalnizca bir sinif eklenir.

Prompt caching / onek mimarisi (bkz. docs/08 §3):
    [system]         donmus rol talimati        -> onbellek siniri
    [context_blocks] sozlesme basina sabit      -> onbellek siniri
    [task_block]     her cagrida degisir        -> isaretsiz

GUVENLIK: her cagri bir Budget muhafizindan gecer. Tavan asilinca model kapatilir
ve BIR DAHA CAGRILMAZ; analiz kural katmaniyla tamamlanir.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from ..config import settings
from .. import runtime_settings as rt
from .budget import Budget, BudgetExceeded

log = logging.getLogger(__name__)

# $ / 1M token (yaklasik; gercek maliyet llm_calls tablosundan izlenir)
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-flash-latest": (0.30, 2.50),
    "gemini-flash-lite-latest": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}
_DEFAULT_PRICE = (1.0, 5.0)


@dataclass
class Turn:
    """Tek bir model cagrisinin butun girdisi."""
    agent: str
    system: str
    task_block: str
    schema: dict[str, Any]
    context_blocks: list[str] = field(default_factory=list)
    effort: str = "medium"          # low | medium | high | xhigh | max
    model: str | None = None
    max_tokens: int = 8000


@dataclass
class Usage:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    ok: bool = True
    error: str = ""

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens


@dataclass
class Completion:
    data: dict[str, Any]
    usage: Usage


class LLMError(RuntimeError):
    """Gecici hata - yeniden denenebilir."""


class LLMPermanentError(LLMError):
    """Kalici hata (kimlik, model yok, sema reddi). YENIDEN DENENMEZ."""


class LLMProvider(Protocol):
    name: str
    is_llm: bool

    def complete_json(self, turn: Turn, budget: Budget | None = None) -> Completion: ...


def fiyat_bilinir(model: str) -> bool:
    return model in PRICING


def fiyat_bul(model: str) -> tuple[float, float] | None:
    """Once kullanicinin girdigi fiyat, sonra yerlesik tablo. Yoksa None."""
    elle = rt.etkin_fiyat()
    if elle is not None:
        return elle
    if model in PRICING:
        return PRICING[model]
    return None


def estimate_cost(u: Usage) -> float:
    """Fiyat bilinmiyorsa 0 doner; rapor bunu '—' olarak gosterir.

    Uydurma bir fiyat yazmaktansa bilinmedigini soylemek dogrudur - ozellikle
    kullanicinin kendi sagladigi bir uc noktada (yerel model, OpenRouter vb.).
    Kullanici arayuzden fiyat girerse o kullanilir ve tablo ezilir.
    """
    fiyat = fiyat_bul(u.model)
    if fiyat is None:
        return 0.0
    inp, out = fiyat
    return (
        u.input_tokens * inp
        + u.cache_read_tokens * inp * 0.1
        + u.cache_write_tokens * inp * 1.25
        + u.output_tokens * out
    ) / 1_000_000


# --------------------------------------------------------------------------- #
class _Guarded:
    """Butce muhafizini tum saglayicilara ortak uygulayan taban sinif."""

    name = "base"
    is_llm = True

    # Kotasi bitmis modeller. Ornek instance'ta paylasilir; ayni analiz icinde
    # tukenen bir modele tekrar tekrar donulmez.
    _tukenmis: set[str]

    def _yedekler(self) -> list[str]:
        return [m.strip() for m in (settings.model_fallbacks or "").split(",") if m.strip()]

    def _sonraki_model(self, mevcut: str) -> str:
        """Kotasi biten modelin yerine gecebilecek ilk yedek."""
        if not hasattr(self, "_tukenmis"):
            self._tukenmis = set()
        self._tukenmis.add(mevcut)
        for m in self._yedekler():
            if m not in self._tukenmis:
                return m
        return ""

    def complete_json(self, turn: Turn, budget: Budget | None = None) -> Completion:
        if budget is not None:
            budget.check()  # tavan asilmissa BudgetExceeded firlatir (yeniden denenmez)

        model = turn.model or ""
        t0 = time.perf_counter()
        try:
            comp = self._dene(turn, budget)
        except LLMPermanentError as exc:
            # Arayuz kullaniciya "anahtarin gecersiz / kotan bitmis" diyebilsin.
            rt.hata_kaydet(rt.hata_turu(str(exc)), str(exc), model, self.name)
            if budget is not None:
                budget.record_failure(
                    permanent=True, reason=f"kalıcı model hatası: {exc}",
                    agent=turn.agent, model=model,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            raise
        except Exception as exc:
            tur = rt.hata_turu(str(exc))
            if tur in ("auth", "quota"):     # gecici de olsa kullaniciyi ilgilendirir
                rt.hata_kaydet(tur, str(exc), model, self.name)
            if budget is not None:
                budget.record_failure(
                    reason=str(exc), agent=turn.agent, model=model,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            raise LLMError(str(exc)) from exc

        rt.hata_temizle()       # calisiyor demek ki
        if budget is not None:
            budget.record_success(comp.usage.cost_usd, comp.usage.total)
        return comp

    def _dene(self, turn: Turn, budget: Budget | None) -> Completion:
        """Gecici hatalarda sinirli yeniden deneme.

        Saglayicilar yuk altinda 503/429 doner; bunlar gecicidir. Yeniden deneme
        olmayinca tek bir 503 devre kesiciye hata yaziyordu ve ust uste ucu tum
        analizi durduruyordu. Kalici hatalar (gecersiz anahtar, biten kota,
        desteklenmeyen model) yeniden DENENMEZ - beklemek bir sey degistirmez.
        """
        son: Exception | None = None
        azami = settings.llm_retry_attempts + len(self._yedekler())

        # Tukenen model hatirlanmazsa her cagri once ona gidip 403 yer; sozlesme
        # basina onlarca bosa gidis-donus demektir. Bilinen tukenmisse dogrudan
        # ilk saglam yedekten baslanir.
        if getattr(self, "_tukenmis", None):
            baslangic = turn.model or rt.etkin_model(self.name) or ""
            if baslangic in self._tukenmis:
                saglam = next((m for m in self._yedekler() if m not in self._tukenmis), "")
                if saglam:
                    turn = replace(turn, model=saglam)

        for deneme in range(azami):
            try:
                return self._invoke(turn)
            except BudgetExceeded:
                raise
            except LLMPermanentError as exc:
                # Kotasi biten ya da istegi kabul etmeyen model, bozuk bir
                # kurulum degildir. Analizi kural katmanina dusurmek yerine
                # siradaki yedek modele gecilir. Gecersiz anahtar ("auth")
                # devredilmez: ayni hata listedeki her modelde tekrarlanir.
                if rt.hata_turu(str(exc)) not in ("quota", "model"):
                    raise
                mevcut = turn.model or rt.etkin_model(self.name) or ""
                yeni = self._sonraki_model(mevcut)
                if not yeni:
                    raise
                log.warning("%s kotasi bitti - yedek modele geciliyor: %s", mevcut, yeni)
                turn = replace(turn, model=yeni)
                rt.hata_temizle()
                continue
            except Exception as exc:                      # gecici
                son = exc
                if deneme >= azami - 1:
                    break
                bekle = settings.llm_retry_backoff_seconds * (2 ** deneme)
                # Sure tavani zaten dolmak uzereyse beklemenin anlami yok.
                if budget is not None and budget.elapsed + bekle >= budget.deadline_seconds:
                    break
                log.info("Gecici model hatasi (%s) - %.0f sn sonra yeniden denenecek (%d/%d)",
                         exc, bekle, deneme + 1, settings.llm_retry_attempts)
                time.sleep(bekle)
        raise son if son is not None else LLMError("model cagrisi basarisiz")

    def _invoke(self, turn: Turn) -> Completion:  # pragma: no cover - arayuz
        raise NotImplementedError


# --------------------------------------------------------------------------- #
class HeuristicProvider:
    """Model erisimi yokken kullanilan saglayici.

    Sahte cevap URETMEZ: is_llm=False oldugu icin analiz katmani model gerektiren
    adimlari atlar ve yalnizca deterministik bulgulari uretir.
    """

    name = "heuristic"
    is_llm = False

    def complete_json(self, turn: Turn, budget: Budget | None = None) -> Completion:
        raise LLMPermanentError(
            "Model sağlayıcısı yapılandırılmamış (API anahtarı yok). Bu adım atlanır."
        )


# --------------------------------------------------------------------------- #
class AnthropicProvider(_Guarded):
    name = "anthropic"
    is_llm = True

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=float(settings.llm_timeout_seconds), max_retries=0
        )

    def _invoke(self, turn: Turn) -> Completion:
        model = turn.model or rt.etkin_model("anthropic")
        system = [{"type": "text", "text": turn.system, "cache_control": {"type": "ephemeral"}}]

        content: list[dict[str, Any]] = []
        for i, block in enumerate(turn.context_blocks):
            part: dict[str, Any] = {"type": "text", "text": block}
            if i == len(turn.context_blocks) - 1:
                part["cache_control"] = {"type": "ephemeral"}
            content.append(part)
        content.append({"type": "text", "text": turn.task_block})

        t0 = time.perf_counter()
        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=turn.max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={
                    "effort": turn.effort,
                    "format": {"type": "json_schema", "schema": turn.schema},
                },
                thinking={"type": "adaptive"},
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (400, 401, 403, 404):
                raise LLMPermanentError(f"HTTP {status}: {exc}") from exc
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        latency = int((time.perf_counter() - t0) * 1000)

        if getattr(resp, "stop_reason", None) == "refusal":
            raise LLMPermanentError("model isteği reddetti (stop_reason=refusal)")

        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        data = _parse_json(text)

        u = resp.usage
        usage = Usage(
            model=model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            latency_ms=latency,
        )
        usage.cost_usd = estimate_cost(usage)
        return Completion(data=data, usage=usage)


# --------------------------------------------------------------------------- #
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(_Guarded):
    """Google Gemini - dogrudan REST (ek bagimlilik yok, zaman asimi tam kontrolde)."""

    name = "gemini"
    is_llm = True

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._no_thinking_config: set[str] = set()  # thinkingConfig kabul etmeyen modeller

    def _invoke(self, turn: Turn) -> Completion:
        model = turn.model or rt.etkin_model("gemini")

        parts = [{"text": b} for b in turn.context_blocks]
        parts.append({"text": turn.task_block})

        gen_cfg: dict[str, Any] = {
            "temperature": 0.1,
            "maxOutputTokens": turn.max_tokens,
            "responseMimeType": "application/json",
            "responseSchema": to_gemini_schema(turn.schema),
        }
        # Dusunme tokeni ciktidan sayilir ve maliyeti buyutur; kapatiyoruz.
        if model not in self._no_thinking_config:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

        body = {
            "systemInstruction": {"parts": [{"text": turn.system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": gen_cfg,
        }

        t0 = time.perf_counter()
        payload = self._post(model, body)
        if payload is None:  # thinkingConfig reddedildi -> bir kez daha, onsuz
            self._no_thinking_config.add(model)
            gen_cfg.pop("thinkingConfig", None)
            payload = self._post(model, body)
            if payload is None:
                raise LLMPermanentError("istek model tarafından kabul edilmedi")
        latency = int((time.perf_counter() - t0) * 1000)

        cands = payload.get("candidates") or []
        if not cands:
            fb = (payload.get("promptFeedback") or {}).get("blockReason")
            raise LLMPermanentError(f"model cevap üretmedi (blockReason={fb})")

        cand = cands[0]
        finish = cand.get("finishReason", "")
        if finish == "MAX_TOKENS":
            raise LLMError("cevap max_tokens sınırında kesildi (JSON eksik)")
        if finish in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise LLMPermanentError(f"model cevabı engelledi (finishReason={finish})")

        text = "".join(
            p.get("text", "") for p in (cand.get("content", {}).get("parts") or [])
        )
        data = _parse_json(text)

        um = payload.get("usageMetadata") or {}
        usage = Usage(
            model=model,
            input_tokens=int(um.get("promptTokenCount", 0) or 0),
            output_tokens=int(um.get("candidatesTokenCount", 0) or 0),
            cache_read_tokens=int(um.get("cachedContentTokenCount", 0) or 0),
            latency_ms=latency,
        )
        usage.cost_usd = estimate_cost(usage)
        return Completion(data=data, usage=usage)

    def _post(self, model: str, body: dict) -> dict | None:
        """None doner = thinkingConfig nedeniyle 400; cagiran onsuz tekrar dener."""
        url = GEMINI_ENDPOINT.format(model=model)
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.llm_timeout_seconds) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            # Bazi modeller thinkingConfig kabul etmez ve genel bir 400 doner.
            # Hata metni acik olmasa da bir kez onsuz denemek gerekir.
            if exc.code == 400 and "thinkingConfig" in json.dumps(body):
                return None
            if exc.code in (400, 401, 403, 404):
                raise LLMPermanentError(f"HTTP {exc.code}: {detail}") from exc
            # 429 (kota) ve 5xx gecicidir; ust uste gelirse devre kesici kapatir.
            raise LLMError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"ağa erişilemedi: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"zaman aşımı ({settings.llm_timeout_seconds} sn)") from exc


class OpenAICompatProvider(_Guarded):
    """OpenAI Chat Completions protokolunu konusan her servis.

    Tek sinif; yalnizca base_url degisir:
      ChatGPT     https://api.openai.com/v1
      DeepSeek    https://api.deepseek.com/v1
      Qwen        https://dashscope-intl.aliyuncs.com/compatible-mode/v1
      Groq        https://api.groq.com/openai/v1
      OpenRouter  https://openrouter.ai/api/v1
      Ollama      http://localhost:11434/v1        (yerel)
      vLLM        http://localhost:8000/v1         (yerel)

    Yapilandirilmis cikti destegi saglayicidan saglayiciya degisir; bu yuzden
    UC KADEMELI geri dusus uygulanir: json_schema -> json_object -> serbest metin.
    Serbest metinde bile `_parse_json` kod blogu sarmalayicilarini temizler.
    """

    name = "openai"
    is_llm = True

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 ad: str = "openai") -> None:
        self._key = api_key
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.name = ad
        self._format_modu: dict[str, str] = {}   # model -> "schema"|"object"|"none"
        self._token_alani: dict[str, str] = {}   # model -> "max_tokens"|"max_completion_tokens"
        self._dusunme: dict[str, bool] = {}      # model -> enable_thinking gonderilsin mi
        self._sicaklik: dict[str, bool] = {}     # model -> temperature kabul ediyor mu
        self._sema_dusuruldu: dict[str, bool] = {}  # model -> sessiz sema ihlali yakalandi mi

    def _invoke(self, turn: Turn) -> Completion:
        model = turn.model or rt.etkin_model(self.name)
        if not model:
            raise LLMPermanentError("Model adı belirtilmedi (bu sağlayıcıda varsayılan yok)")

        icerik = "\n\n".join(list(turn.context_blocks) + [turn.task_block])
        mesajlar = [
            {"role": "system", "content": turn.system +
             "\n\nCevabını YALNIZCA geçerli bir JSON nesnesi olarak ver; "
             "açıklama, ön söz veya kod bloğu işareti ekleme."},
            {"role": "user", "content": icerik},
        ]

        mod = self._format_modu.get(model, "schema")
        alan = self._token_alani.get(model, "max_tokens")

        t0 = time.perf_counter()
        for _ in range(4):     # her geri dusus icin bir deneme
            govde: dict[str, Any] = {
                "model": model,
                "messages": mesajlar,
                alan: turn.max_tokens,
            }
            # Bazi modeller (kimi-k3) temperature kabul etmiyor. Reddedildigi
            # ogrenilince bu model icin bir daha gonderilmez; govde her dongude
            # bastan kuruldugu icin yalnizca sozlukten silmek yetmiyordu.
            if self._sicaklik.get(model, True):
                govde["temperature"] = 0.1
            # Qwen3 ve benzeri modellerde dusunme modu varsayilan olarak aciktir:
            # cikti uc katina cikar, gecikme dort katina. Bu is icin akil yurutme
            # zinciri gerekmiyor; kapatilinca 19 sn -> 5 sn, 994 -> 400 token.
            # Desteklemeyen servis 400 doner, asagidaki geri dusus onsuz tekrar dener.
            if self._dusunme.get(model, _dusunme_kapatilabilir(model)):
                govde["enable_thinking"] = False
            if mod == "schema":
                govde["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "cikti", "strict": True,
                                    "schema": _strict_schema(turn.schema)},
                }
            elif mod == "object":
                govde["response_format"] = {"type": "json_object"}

            # Sunucu tarafinda sema zorlanamadigi kipte (object/none) model alan
            # adlarini bilemez ve cikti sessizce bosa duser. Semayi metin olarak
            # promta koyariz: zorlama degil ama sekli tarif eder.
            govde["messages"] = _semali_mesajlar(mesajlar, turn.schema, mod)

            try:
                payload = self._post(govde)
                break
            except _Uyumsuz as exc:
                if exc.tur == "format" and mod == "schema":
                    mod = "object"
                elif exc.tur == "format" and mod == "object":
                    mod = "none"
                elif exc.tur == "dusunme":
                    self._dusunme[model] = False      # bu model kabul etmiyor
                    continue
                elif exc.tur == "token_alani" and alan == "max_tokens":
                    alan = "max_completion_tokens"
                elif exc.tur == "sicaklik":
                    self._sicaklik[model] = False     # bu model kabul etmiyor
                    continue
                else:
                    raise LLMPermanentError(str(exc)) from exc
        else:
            raise LLMPermanentError("İstek bu sağlayıcı tarafından kabul edilmedi")

        self._format_modu[model] = mod
        self._token_alani[model] = alan
        self._sicaklik.setdefault(model, True)
        latency = int((time.perf_counter() - t0) * 1000)

        secenekler = payload.get("choices") or []
        if not secenekler:
            raise LLMPermanentError("Model cevap üretmedi")
        ileti = secenekler[0].get("message") or {}
        if secenekler[0].get("finish_reason") == "length":
            raise LLMError("cevap max_tokens sınırında kesildi (JSON eksik)")
        data = _parse_json(ileti.get("content") or "")

        # Sessiz sema ihlali: uc, json_schema'yi kabul edip yok saymis olabilir.
        # Zorunlu ust duzey alanlar donmediyse bu modeli object kipine indir ve
        # bir kez daha dene; sema metni zaten promtta oldugu icin ikinci deneme
        # dogru sekli uretir.
        gerekli = list((turn.schema or {}).get("required") or [])
        if gerekli and not any(k in data for k in gerekli) and not self._sema_dusuruldu.get(model):
            self._sema_dusuruldu[model] = True
            self._format_modu[model] = "object"
            log.warning("%s semayi yok saydi (donen alanlar: %s) - object kipinde tekrar deneniyor",
                        model, ", ".join(list(data)[:5]) or "yok")
            return self._invoke(turn)

        u = payload.get("usage") or {}
        detay = u.get("prompt_tokens_details") or {}
        usage = Usage(
            model=model,
            input_tokens=int(u.get("prompt_tokens", 0) or 0),
            output_tokens=int(u.get("completion_tokens", 0) or 0),
            cache_read_tokens=int(detay.get("cached_tokens", 0) or 0),
            latency_ms=latency,
        )
        usage.cost_usd = estimate_cost(usage)
        return Completion(data=data, usage=usage)

    def _post(self, govde: dict) -> dict:
        req = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.llm_timeout_seconds) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            detay = ""
            try:
                detay = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if exc.code == 400:
                d = detay.lower()
                if "response_format" in d or "json_schema" in d or "schema" in d:
                    raise _Uyumsuz("format", detay) from exc
                if "max_completion_tokens" in d or "max_tokens" in d:
                    raise _Uyumsuz("token_alani", detay) from exc
                if "temperature" in d:
                    raise _Uyumsuz("sicaklik", detay) from exc
                if "enable_thinking" in d or "thinking" in d:
                    raise _Uyumsuz("dusunme", detay) from exc
            if exc.code in (400, 401, 403, 404):
                raise LLMPermanentError(f"HTTP {exc.code}: {detay}") from exc
            raise LLMError(f"HTTP {exc.code}: {detay}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"ağa erişilemedi: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"zaman aşımı ({settings.llm_timeout_seconds} sn)") from exc


def _dusunme_kapatilabilir(model: str) -> bool:
    """Bu model adi dusunme modunu acik varsayan bir aileden mi?

    Qwen3+, GLM, Kimi, DeepSeek gibi aileler dusunme modunu varsayilan ACIK
    kabul eder. Bu is icin akil yurutme zinciri gerekmiyor ve pahali: acikken
    glm-5.2-fast-preview cagri basina ~3.900 cikti tokeni ve 39 saniye
    harciyordu, kapaliyken ayni is ~650 tokene iniyor.

    Bu yuzden metin ureten HER modelde bir kez denenir; servis alani
    reddederse `_dusunme` sozlugune yazilir ve bir daha gonderilmez. Yalniz
    metin uretmeyen modellerde (gorsel, ses, gomme) hic denenmez.
    """
    m = model.lower()
    return not any(
        k in m for k in ("image", "audio", "embedding", "rerank", "ocr",
                         "tts", "asr", "vl-", "omni", "wan", "lyria", "banana"))


class _Uyumsuz(RuntimeError):
    """Saglayici bu alani desteklemiyor; geri dusulmeli."""

    def __init__(self, tur: str, detay: str = "") -> None:
        super().__init__(detay or tur)
        self.tur = tur


def _semali_mesajlar(mesajlar: list[dict], schema: dict | None, mod: str) -> list[dict]:
    """Semayi kullanici iletisinin sonuna metin olarak ekler.

    Kipten bagimsiz eklenir. Bazi OpenAI-uyumlu uclar (Qwen'in maas ucu gibi)
    `response_format: json_schema` istegini 200 ile kabul edip semayi SESSIZCE yok
    sayar; cikti gecerli JSON'dur ama alan adlari bambaskadir ve tum bulgular bosa
    duser. Semayi ayrica metin olarak vermek bu sessiz basarisizligi kapatir.
    """
    if not schema:
        return mesajlar
    ek = ("\n\n=== CIKTI SEMASI (bu JSON semasina birebir uy; "
          "alan adlarini degistirme, fazladan alan ekleme) ===\n"
          + json.dumps(schema, ensure_ascii=False))
    out = [dict(m) for m in mesajlar]
    out[-1]["content"] = out[-1]["content"] + ek
    return out


def _strict_schema(schema: dict) -> dict:
    """OpenAI strict modu her nesnede additionalProperties:false ve tam required ister."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object":
        ozellikler = out.get("properties") or {}
        out["properties"] = {k: _strict_schema(v) for k, v in ozellikler.items()}
        out["required"] = list(ozellikler.keys())
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = _strict_schema(out["items"])
    return out


_TYPE_MAP = {
    "object": "OBJECT", "array": "ARRAY", "string": "STRING",
    "number": "NUMBER", "integer": "INTEGER", "boolean": "BOOLEAN",
}


def to_gemini_schema(schema: dict) -> dict:
    """JSON Schema -> Gemini responseSchema (OpenAPI alt kumesi).

    Gemini `additionalProperties` kabul etmez ve tip adlarini buyuk harf bekler.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "additionalProperties":
            continue
        if k == "type" and isinstance(v, str):
            out["type"] = _TYPE_MAP.get(v.lower(), v.upper())
        elif k == "properties" and isinstance(v, dict):
            out["properties"] = {pk: to_gemini_schema(pv) for pk, pv in v.items()}
            out.setdefault("propertyOrdering", list(v.keys()))
        elif k == "items":
            out["items"] = to_gemini_schema(v)
        elif k in ("required", "enum", "description", "nullable", "format"):
            out[k] = v
    return out


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise LLMError("model boş cevap döndü")
    if text.startswith("```"):  # bazi modeller kod bloguna sarar
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"cevap geçerli JSON değil: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("cevap bir JSON nesnesi değil")
    return data


# --------------------------------------------------------------------------- #
_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider

    choice = rt.etkin_saglayici()

    def _gemini() -> LLMProvider | None:
        anahtar = rt.etkin_anahtar("gemini")
        if not anahtar:
            return None
        log.info("LLM saglayici: gemini (%s)", rt.etkin_model("gemini"))
        return GeminiProvider(anahtar)

    def _anthropic() -> LLMProvider | None:
        anahtar = rt.etkin_anahtar("anthropic")
        if not anahtar:
            return None
        try:
            p = AnthropicProvider(anahtar)
            log.info("LLM saglayici: anthropic (%s)", rt.etkin_model("anthropic"))
            return p
        except Exception as exc:
            log.warning("Anthropic saglayici kurulamadi: %s", exc)
            return None

    def _openai(ad: str = "openai") -> LLMProvider | None:
        anahtar = rt.etkin_anahtar(ad)
        temel = rt.etkin_base_url(ad)
        if not anahtar and "localhost" not in temel and "127.0.0.1" not in temel:
            return None
        log.info("LLM saglayici: %s (%s @ %s)", ad, rt.etkin_model(ad), temel)
        return OpenAICompatProvider(anahtar or "yok", temel, ad=ad)

    if choice == "heuristic":
        _provider = HeuristicProvider()
    elif choice == "gemini":
        _provider = _gemini() or HeuristicProvider()
    elif choice == "anthropic":
        _provider = _anthropic() or HeuristicProvider()
    elif choice in ("openai", "custom"):
        _provider = _openai(choice) or HeuristicProvider()
    else:  # auto
        _provider = (_anthropic() or _gemini() or _openai()
                     or HeuristicProvider())

    if not _provider.is_llm:
        log.info("Model anahtari yok - kural tabanli mod")
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None


def active_model(provider: LLMProvider) -> str | None:
    """Saglayicinin fiilen kullandigi model - saglik ucu ve raporlama icin."""
    if provider.name in ("gemini", "anthropic", "openai", "custom"):
        return rt.etkin_model(provider.name)
    return None


def cheap_model(provider: LLMProvider) -> str | None:
    """Ucuz gorevler icin (siniflandirma, meta) kullanilacak model."""
    if provider.name == "gemini":
        return settings.model_gemini_cheap
    if provider.name == "anthropic":
        return settings.model_cheap
    return None


def dogrula(saglayici: str, anahtar: str, model: str,
            base_url: str = "") -> tuple[bool, str]:
    """Girilen anahtar/model gercekten calisiyor mu? Tek kucuk cagri yapar."""
    if saglayici == "gemini":
        p: LLMProvider = GeminiProvider(anahtar)
    elif saglayici == "anthropic":
        p = AnthropicProvider(anahtar)
    elif saglayici in ("openai", "custom"):
        p = OpenAICompatProvider(anahtar, base_url or rt.etkin_base_url(saglayici),
                                 ad=saglayici)
    else:
        return False, "Doğrulanacak sağlayıcı seçilmedi"

    turn = Turn(
        agent="Dogrulama", system="Yalnızca verilen JSON şemasına uygun çıktı üret.",
        task_block="Bu bir bağlantı testidir. ok alanına true yaz.",
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"], "additionalProperties": False},
        # Sema zorlamasi kucuk cevaplarda bile birkac yuz token isteyebilir;
        # dar bir tavan "gecerli anahtar"i basarisiz gosterirdi.
        model=model or None, max_tokens=512,
    )
    try:
        c = p.complete_json(turn, Budget(max_calls=1, max_cost_usd=0.01))
        u = c.usage
        return True, (f"Bağlantı başarılı · {u.model} · "
                      f"{u.input_tokens}/{u.output_tokens} token · {u.latency_ms} ms")
    except LLMPermanentError as exc:
        return False, f"Kalıcı hata: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
