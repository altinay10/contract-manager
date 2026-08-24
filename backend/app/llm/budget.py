"""Model harcamasi icin sert tavanlar (butce muhafizi).

Neden gerekli: bir analiz takilirsa, dongude kalirsa ya da model beklenmedik
sekilde uzun cevap uretirse, fark edilmeden yuksek maliyet olusabilir. Bu modul
harcamayi TEK BIR YERDEN sinirlar ve tavan asildiginda model cagrilarini
tamamen kapatir - yeniden denemez.

Tasarim ilkesi: butce asilinca analiz COKMEZ. Model kapatilir, kural katmani
devam eder ve rapora "model butcesi doldu" notu duser. Kullanici eli bos kalmaz.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from ..config import settings

log = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """Tavan asildi. Bu istisna YENIDEN DENENMEZ."""


class CircuitOpen(RuntimeError):
    """Ust uste hata: devre kesildi, model cagrilari durduruldu."""


@dataclass
class Budget:
    """Tek bir sozlesme analizinin model butcesi."""

    max_calls: int = field(default_factory=lambda: settings.max_llm_calls)
    max_cost_usd: float = field(default_factory=lambda: settings.max_cost_usd)
    max_total_tokens: int = field(default_factory=lambda: settings.max_total_tokens)
    deadline_seconds: int = field(default_factory=lambda: settings.llm_deadline_seconds)
    max_consecutive_failures: int = field(
        default_factory=lambda: settings.max_consecutive_failures
    )

    calls: int = 0
    cost_usd: float = 0.0
    total_tokens: int = 0
    consecutive_failures: int = 0
    started_at: float = field(default_factory=time.monotonic)
    disabled_reason: str = ""
    # Basarisiz cagrilar da kayda gecer: rapor "model denendi ama olmadi" diyebilsin.
    failures: list[dict] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------ #
    @property
    def active(self) -> bool:
        return not self.disabled_reason

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.calls)

    def check(self) -> None:
        """Cagri oncesi kontrol. Tavan asilmissa BudgetExceeded firlatir."""
        with self._lock:
            if self.disabled_reason:
                raise BudgetExceeded(self.disabled_reason)

            if self.calls >= self.max_calls:
                self._disable(f"model çağrısı tavanı doldu ({self.max_calls})")
            elif self.cost_usd >= self.max_cost_usd:
                self._disable(f"maliyet tavanı doldu (${self.max_cost_usd:.2f})")
            elif self.total_tokens >= self.max_total_tokens:
                self._disable(f"token tavanı doldu ({self.max_total_tokens:,})")
            elif self.elapsed >= self.deadline_seconds:
                self._disable(f"süre tavanı doldu ({self.deadline_seconds} sn)")
            elif self.consecutive_failures >= self.max_consecutive_failures:
                self._disable(
                    f"üst üste {self.consecutive_failures} model hatası — devre kesildi"
                )

            if self.disabled_reason:
                raise BudgetExceeded(self.disabled_reason)

    def _disable(self, reason: str) -> None:
        """Kilit ZATEN tutuluyorken cagrilir."""
        if not self.disabled_reason:
            self.disabled_reason = reason
            log.warning("MODEL KAPATILDI: %s (çağrı=%d, maliyet=$%.4f, token=%d)",
                        reason, self.calls, self.cost_usd, self.total_tokens)

    def record_success(self, cost_usd: float, tokens: int) -> None:
        with self._lock:
            self.calls += 1
            self.cost_usd += cost_usd
            self.total_tokens += tokens
            self.consecutive_failures = 0

    def record_failure(self, permanent: bool = False, reason: str = "",
                       agent: str = "", model: str = "", latency_ms: int = 0) -> None:
        with self._lock:
            self.calls += 1
            self.consecutive_failures += 1
            self.failures.append({
                "agent": agent or "?", "model": model or "",
                "error": (reason or "hata")[:400], "latency_ms": latency_ms,
                "permanent": permanent,
            })
            if permanent:
                self._disable(reason or "kalıcı hata (kimlik veya kota)")

    def disable(self, reason: str) -> None:
        with self._lock:
            self._disable(reason)

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "failed_calls": len(self.failures),
            "cost_usd": round(self.cost_usd, 4),
            "total_tokens": self.total_tokens,
            "elapsed_seconds": round(self.elapsed, 1),
            "disabled_reason": self.disabled_reason,
            "limits": {
                "max_calls": self.max_calls,
                "max_cost_usd": self.max_cost_usd,
                "max_total_tokens": self.max_total_tokens,
                "deadline_seconds": self.deadline_seconds,
            },
        }
