"""
LLMClient testleri — OpenAI API'si mocklıdır.
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
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
    with patch("src.intelligence.llm_client.openai.OpenAI") as MockOpenAI:
        mock_api = MagicMock()
        MockOpenAI.return_value = mock_api
        c = LLMClient()
        c._mock_api = mock_api
        yield c


def _make_api_response(input_tokens: int = 100, output_tokens: int = 50, text: str = "Merhaba"):
    resp = MagicMock()
    resp.usage.prompt_tokens = input_tokens
    resp.usage.completion_tokens = output_tokens
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


# ── Başarılı çağrı ─────────────────────────────────────────────────────────────

class TestLLMClientCall:
    def test_returns_llm_response(self, client, tmp_db):
        client._client.chat.completions.create.return_value = _make_api_response(
            input_tokens=200, output_tokens=80, text="Test yanıt"
        )
        resp = client.call(agent="research", messages=[{"role": "user", "content": "Merhaba"}])

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Test yanıt"
        assert resp.input_tokens == 200
        assert resp.output_tokens == 80
        assert resp.total_tokens == 280

    def test_cost_is_logged(self, client, tmp_db):
        client._client.chat.completions.create.return_value = _make_api_response(
            input_tokens=1_000_000, output_tokens=500_000
        )
        resp = client.call(agent="research", messages=[{"role": "user", "content": "x"}])

        # gpt-4o-mini: input 0.15/M, output 0.60/M → 1M*0.15 + 0.5M*0.60 = 0.15 + 0.30 = 0.45
        assert abs(resp.cost_usd - 0.45) < 0.001

        row = tmp_db.fetchone("SELECT * FROM llm_calls")
        assert row is not None
        assert row["agent"] == "research"
        assert row["success"] == 1
        assert row["input_tokens"] == 1_000_000

    def test_system_prompt_in_messages(self, client, tmp_db):
        client._client.chat.completions.create.return_value = _make_api_response()
        client.call(
            agent="analyst",
            messages=[{"role": "user", "content": "q"}],
            system="Sen bir analistsin.",
        )
        call_kwargs = client._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0] == {"role": "system", "content": "Sen bir analistsin."}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "q"}

    def test_failure_is_logged(self, client, tmp_db):
        client._client.chat.completions.create.side_effect = RuntimeError("api error")

        with pytest.raises(RuntimeError):
            client.call(agent="research", messages=[{"role": "user", "content": "x"}])

        row = tmp_db.fetchone("SELECT * FROM llm_calls")
        assert row is not None
        assert row["success"] == 0
        assert "api error" in row["error_message"]


# ── Bütçe kontrolü ────────────────────────────────────────────────────────────

class TestBudgetEnforcement:
    def test_raises_when_daily_budget_exceeded(self, client, tmp_db):
        today = date.today().isoformat()
        tmp_db.log_llm_call({
            "agent": "research",
            "model": "gpt-4o-mini",
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

        client._client.chat.completions.create.assert_not_called()

    def test_passes_when_within_budget(self, client, tmp_db):
        client._client.chat.completions.create.return_value = _make_api_response()
        resp = client.call(agent="research", messages=[{"role": "user", "content": "x"}])
        assert resp.content is not None


# ── Maliyet hesabı ────────────────────────────────────────────────────────────

class TestComputeCost:
    def test_gpt4o_mini_pricing(self, client):
        cost = client.compute_cost(input_tokens=1_000_000, output_tokens=1_000_000)
        assert abs(cost - 0.75) < 0.001  # 0.15 + 0.60

    def test_zero_tokens(self, client):
        assert client.compute_cost(0, 0) == 0.0
