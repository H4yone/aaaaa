"""
OpenAI istemcisi — token bütçesi, maliyet logu, yeniden deneme.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import openai
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
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4o-2024-11-20": {"input": 2.50,  "output": 10.00},
    "o1-mini":           {"input": 3.00,  "output": 12.00},
    "o1":                {"input": 15.00, "output": 60.00},
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
    OpenAI SDK wrapper.

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

        self._client = openai.OpenAI()  # OPENAI_API_KEY env'den okunur

    # ── Bütçe yönetimi ────────────────────────────────────────────────────────

    def _check_budget(self) -> None:
        # Bütçe gerçek token kullanımıyla (input+output) karşılaştırılır; fiyat
        # dönüşümü yapılmaz — aksi halde çıktı maliyeti göz ardı edilirdi.
        today = date.today().isoformat()
        year_month = today[:7]
        db = get_db()

        daily_tokens = db.get_daily_llm_tokens(today)
        monthly_tokens = db.get_monthly_llm_tokens(year_month)

        if daily_tokens >= self._daily_token_budget:
            raise BudgetExceeded(
                f"Günlük bütçe aşıldı: {daily_tokens:,} / {self._daily_token_budget:,} token"
            )
        if monthly_tokens >= self._monthly_token_budget:
            raise BudgetExceeded(
                f"Aylık bütçe aşıldı: {monthly_tokens:,} / {self._monthly_token_budget:,} token"
            )

    # ── Maliyet hesabı ────────────────────────────────────────────────────────

    def compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        price = _PRICING.get(self.model, _PRICING["gpt-4o-mini"])
        return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000

    # ── API çağrısı ───────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(openai.RateLimitError),
        reraise=True,
    )
    def call(
        self,
        agent: str,
        messages: list[dict],
        system: str | None = None,
    ) -> LLMResponse:
        """
        OpenAI'ya mesaj gönder, token kullanımını logla.

        Args:
            agent: "research" | "analyst" | "narrative" | "content" | "feedback"
            messages: [{"role": "user"/"assistant", "content": "..."}]
            system: Sistem istemi (opsiyonel) — messages listesinin başına eklenir
        """
        self._check_budget()

        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        start = time.monotonic()
        input_tokens = output_tokens = 0
        content = ""
        success = True
        error_message: str | None = None

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=full_messages,
            )
            input_tokens = resp.usage.prompt_tokens
            output_tokens = resp.usage.completion_tokens
            content = resp.choices[0].message.content

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
