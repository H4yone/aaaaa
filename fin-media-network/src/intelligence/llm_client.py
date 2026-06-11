"""
Anthropic Claude istemcisi — token bütçesi, maliyet logu, yeniden deneme.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anthropic
import yaml
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.db.database import get_db

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

# Fiyatlar: USD / 1 milyon token
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-opus-4-8":           {"input": 15.00, "output": 75.00},
}


class BudgetExceeded(Exception):
    """Günlük veya aylık token bütçesi aşıldığında."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: int


class LLMClient:
    """
    Anthropic SDK wrapper.

    - settings.yaml'dan model / bütçe okur
    - Her çağrıyı llm_calls tablosuna loglar
    - Günlük / aylık USD maliyet bütçesi aşılırsa BudgetExceeded fırlatır
    - RateLimitError'da tenacity ile 3 kez yeniden dener
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        cfg_path = Path(config_path) if config_path else _CONFIG_PATH
        llm_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["llm"]

        self.model: str = llm_cfg["model"]
        self.max_tokens: int = llm_cfg["max_tokens"]
        self.temperature: float = llm_cfg["temperature"]
        self._daily_token_budget: int = llm_cfg["daily_token_budget"]
        self._monthly_token_budget: int = llm_cfg["monthly_token_budget"]

        self._client = anthropic.Anthropic()  # ANTHROPIC_API_KEY env'den okunur

    # ── Bütçe yönetimi ────────────────────────────────────────────────────────

    def _token_budget_to_usd(self, tokens: int) -> float:
        """Token sayısını tahmini USD maliyete çevirir (input fiyatı baz alır)."""
        price = _PRICING.get(self.model, _PRICING["claude-haiku-4-5-20251001"])
        return tokens / 1_000_000 * price["input"]

    def _check_budget(self) -> None:
        today = date.today().isoformat()
        year_month = today[:7]
        db = get_db()

        daily_spent = db.get_daily_llm_cost(today)
        monthly_spent = db.get_monthly_llm_cost(year_month)

        daily_limit = self._token_budget_to_usd(self._daily_token_budget)
        monthly_limit = self._token_budget_to_usd(self._monthly_token_budget)

        if daily_spent >= daily_limit:
            raise BudgetExceeded(
                f"Günlük bütçe aşıldı: ${daily_spent:.4f} / ${daily_limit:.4f}"
            )
        if monthly_spent >= monthly_limit:
            raise BudgetExceeded(
                f"Aylık bütçe aşıldı: ${monthly_spent:.4f} / ${monthly_limit:.4f}"
            )

    # ── Maliyet hesabı ────────────────────────────────────────────────────────

    def compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        price = _PRICING.get(self.model, _PRICING["claude-haiku-4-5-20251001"])
        return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000

    # ── API çağrısı ───────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(anthropic.RateLimitError),
        reraise=True,
    )
    def call(
        self,
        agent: str,
        messages: list[dict],
        system: str | None = None,
    ) -> LLMResponse:
        """
        Claude'a mesaj gönder, token kullanımını logla.

        Args:
            agent: "research" | "analyst" | "narrative" | "content" | "feedback"
            messages: [{"role": "user"/"assistant", "content": "..."}]
            system: Sistem istemi (opsiyonel)
        """
        self._check_budget()

        start = time.monotonic()
        input_tokens = output_tokens = 0
        content = ""
        success = True
        error_message: str | None = None

        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system

            resp = self._client.messages.create(**kwargs)
            input_tokens = resp.usage.input_tokens
            output_tokens = resp.usage.output_tokens
            content = resp.content[0].text

        except Exception as exc:
            success = False
            error_message = str(exc)
            raise

        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            total_tokens = input_tokens + output_tokens
            cost_usd = self.compute_cost(input_tokens, output_tokens)

            try:
                get_db().log_llm_call({
                    "agent": agent,
                    "model": self.model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cost_usd": cost_usd,
                    "duration_ms": duration_ms,
                    "success": 1 if success else 0,
                    "error_message": error_message,
                })
            except Exception:
                logger.exception("LLM çağrısı loglanamadı (agent=%s)", agent)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
        )
