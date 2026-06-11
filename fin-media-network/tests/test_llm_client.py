"""
LLMClient testleri — Anthropic API'si mocklıdır.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import reset_db
from src.intelligence.llm_client import BudgetExceeded, LLMClient, LLMResponse


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


@pytest.fixture()
def client(tmp_db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
    # Anthropic SDK'yı mock et — gerçek HTTP isteği yapmaz
    with patch("src.intelligence.llm_client.anthropic.Anthropic") as MockAnthropic:
        mock_api = MagicMock()
        MockAnthropic.return_value = mock_api
        c = LLMClient()
        c._mock_api = mock_api  # testlerde erişim için
        yield c


def _make_api_response(input_tokens: int = 100, output_tokens: int = 50, text: str = "Merhaba"):
    msg = MagicMock()
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    msg.content = [MagicMock(text=text)]
    return msg


# ── Başarılı çağrı ─────────────────────────────────────────────────────────────

class TestLLMClientCall:
    def test_returns_llm_response(self, client, tmp_db):
        client._client.messages.create.return_value = _make_api_response(
            input_tokens=200, output_tokens=80, text="Test yanıt"
        )
        resp = client.call(agent="research", messages=[{"role": "user", "content": "Merhaba"}])

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Test yanıt"
        assert resp.input_tokens == 200
        assert resp.output_tokens == 80
        assert resp.total_tokens == 280

    def test_cost_is_logged(self, client, tmp_db):
        client._client.messages.create.return_value = _make_api_response(
            input_tokens=1_000_000, output_tokens=500_000
        )
        resp = client.call(agent="research", messages=[{"role": "user", "content": "x"}])

        # haiku: input 0.80/M, output 4.00/M → 1M*0.8 + 0.5M*4 = 0.80 + 2.00 = 2.80
        assert abs(resp.cost_usd - 2.80) < 0.001

        row = tmp_db.fetchone("SELECT * FROM llm_calls")
        assert row is not None
        assert row["agent"] == "research"
        assert row["success"] == 1
        assert row["input_tokens"] == 1_000_000

    def test_system_prompt_forwarded(self, client, tmp_db):
        client._client.messages.create.return_value = _make_api_response()
        client.call(
            agent="analyst",
            messages=[{"role": "user", "content": "q"}],
            system="Sen bir analistsin.",
        )
        call_kwargs = client._client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Sen bir analistsin."

    def test_failure_is_logged(self, client, tmp_db):
        client._client.messages.create.side_effect = RuntimeError("api error")

        with pytest.raises(RuntimeError):
            client.call(agent="research", messages=[{"role": "user", "content": "x"}])

        row = tmp_db.fetchone("SELECT * FROM llm_calls")
        assert row is not None
        assert row["success"] == 0
        assert "api error" in row["error_message"]


# ── Bütçe kontrolü ────────────────────────────────────────────────────────────

class TestBudgetEnforcement:
    def test_raises_when_daily_budget_exceeded(self, client, tmp_db):
        # Haiku input fiyatı 0.80/M → 30_000 token limit = $0.000024
        # DB'ye 1 dolar harcatarak limiti aş
        today = date.today().isoformat()
        tmp_db.log_llm_call({
            "agent": "research",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 999.0,  # kesinlikle aşar
            "duration_ms": 10,
            "success": 1,
            "error_message": None,
        })

        with pytest.raises(BudgetExceeded, match="Günlük"):
            client.call(agent="research", messages=[{"role": "user", "content": "x"}])

        # API çağrısı yapılmamış olmalı
        client._client.messages.create.assert_not_called()

    def test_passes_when_within_budget(self, client, tmp_db):
        client._client.messages.create.return_value = _make_api_response()
        # Harcama yok → bütçe içinde
        resp = client.call(agent="research", messages=[{"role": "user", "content": "x"}])
        assert resp.content is not None


# ── Maliyet hesabı ────────────────────────────────────────────────────────────

class TestComputeCost:
    def test_haiku_pricing(self, client):
        cost = client.compute_cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert abs(cost - 4.80) < 0.001  # 0.80 + 4.00

    def test_zero_tokens(self, client):
        assert client.compute_cost(0, 0) == 0.0
