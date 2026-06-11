"""
AnalystAgent testleri — LLM ve DB mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src.db.database import reset_db
from src.intelligence.analyst_agent import AnalystAgent
from src.intelligence.llm_client import BudgetExceeded, LLMResponse


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _mock_llm(body: dict | None = None) -> MagicMock:
    if body is None:
        body = {
            "scenarios": {
                "bull": {
                    "probability": 0.2,
                    "description": "Risk iştahı artar, BIST yükselir.",
                    "stocks": [{"ticker": "XU030.IS", "direction": "yukarı", "reasoning": "Fon girişi"}],
                },
                "base": {
                    "probability": 0.5,
                    "description": "Piyasa sınırlı tepki verir.",
                    "stocks": [{"ticker": "GARAN.IS", "direction": "aşağı", "reasoning": "Baskı"}],
                },
                "bear": {
                    "probability": 0.3,
                    "description": "Sert satış dalgası.",
                    "stocks": [{"ticker": "GARAN.IS", "direction": "aşağı", "reasoning": "Panic sell"}],
                },
            },
            "time_horizon": "ayni_gun",
            "trigger_conditions_active": True,
            "key_risk": "Fed beklenenden sert çıkarsa TRY sert zayıflar.",
            "key_opportunity": "Dovish sürpriz bankacılık sektörüne hızlı yukarı iter.",
        }
    llm = MagicMock()
    llm.call.return_value = LLMResponse(
        content=json.dumps(body),
        input_tokens=600,
        output_tokens=200,
        total_tokens=800,
        cost_usd=0.001,
        duration_ms=900,
    )
    return llm


def _seed_signal(db, date_str: str, rule_ids: list[str] | None = None) -> int:
    cluster_id = db.insert_cluster({
        "date": date_str,
        "representative_title": "Fed hawkish, faiz artışı beklentisi güçlendi",
        "news_count": 3,
        "source_weight": 0.9,
        "market_relevance": 0.85,
        "volatility_impact": 0.75,
        "score": 78.0,
        "tier": 1,
        "keywords": json.dumps(["hawkish", "rate hike"]),
        "tickers_mentioned": json.dumps(["^TNX"]),
    })
    return db.insert_signal({
        "date": date_str,
        "cluster_id": cluster_id,
        "headline": "Fed faizi artırıyor, BIST baskı altında kalabilir",
        "what_happened": "Fed 25 baz puan faiz artışı yaptı.",
        "why_it_matters": "EM'den fon çıkışı BIST'i olumsuz etkiler.",
        "bias": "bearish",
        "confidence": 0.78,
        "transmission_rule_ids": json.dumps(rule_ids or ["fed_hawkish"]),
        "bist_impact_json": json.dumps({
            "overall": "negatif",
            "sectors": [
                {"sector": "bankacılık", "stocks": ["GARAN.IS"], "direction": "aşağı", "reasoning": "..."}
            ],
        }),
        "rank": 1,
    })


def _seed_market(db, date_str: str, ticker: str = "^TNX",
                  close: float = 4.55, change_pct: float = 0.08) -> None:
    db.insert_market_snapshot({
        "date": date_str,
        "ticker": ticker,
        "open": close - 0.05,
        "high": close + 0.03,
        "low": close - 0.06,
        "close": close,
        "volume": None,
        "change_pct": change_pct,
        "source": "yfinance",
        "extra_json": None,
    })


# ── Trigger koşul değerlendirme ───────────────────────────────────────────────

class TestEvaluateConditions:
    def test_condition_met_when_above_threshold(self, tmp_db):
        agent = AnalystAgent(llm_client=MagicMock())
        rule = {
            "id": "fed_hawkish",
            "trigger_condition": {"dgs10_change_pct": ">0.05"},
        }
        market = {"^TNX": {"close": 4.55, "change_pct": 0.08}}
        results = agent._evaluate_conditions(rule, market)
        assert len(results) == 1
        assert results[0]["met"] is True
        assert results[0]["actual"] == 0.08

    def test_condition_not_met_when_below_threshold(self, tmp_db):
        agent = AnalystAgent(llm_client=MagicMock())
        rule = {
            "id": "fed_hawkish",
            "trigger_condition": {"dgs10_change_pct": ">0.05"},
        }
        market = {"^TNX": {"close": 4.50, "change_pct": 0.02}}
        results = agent._evaluate_conditions(rule, market)
        assert results[0]["met"] is False

    def test_vix_uses_close_not_change_pct(self, tmp_db):
        agent = AnalystAgent(llm_client=MagicMock())
        rule = {
            "id": "nasdaq_rally",
            "trigger_condition": {"vix_level": "<18"},
        }
        market = {"^VIX": {"close": 15.5, "change_pct": -2.1}}
        results = agent._evaluate_conditions(rule, market)
        # close=15.5 < 18 → met
        assert results[0]["met"] is True
        assert results[0]["actual"] == 15.5

    def test_missing_market_data_returns_not_met(self, tmp_db):
        agent = AnalystAgent(llm_client=MagicMock())
        rule = {
            "id": "oil_up",
            "trigger_condition": {"cl_change_pct": ">2.0"},
        }
        results = agent._evaluate_conditions(rule, {})
        assert results[0]["met"] is False
        assert results[0]["actual"] is None

    def test_no_trigger_conditions_returns_empty(self, tmp_db):
        agent = AnalystAgent(llm_client=MagicMock())
        rule = {"id": "geopolitical_risk", "trigger_condition": {}}
        results = agent._evaluate_conditions(rule, {})
        assert results == []


# ── Tam çalışma döngüsü ───────────────────────────────────────────────────────

class TestAnalystAgentRun:
    def test_creates_content_for_signal(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        signal_id = _seed_signal(tmp_db, today)
        _seed_market(tmp_db, today)

        agent = AnalystAgent(llm_client=_mock_llm())
        content_ids = agent.run(date.today())

        assert len(content_ids) == 1
        row = tmp_db.fetchone("SELECT * FROM content WHERE id=?", (content_ids[0],))
        assert row["platform"] == "analyst_brief"
        assert row["compliance_passed"] == 1

    def test_body_contains_scenarios(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)
        _seed_market(tmp_db, today)

        agent = AnalystAgent(llm_client=_mock_llm())
        content_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT body FROM content WHERE id=?", (content_ids[0],))
        body = json.loads(row["body"])
        assert "scenarios" in body
        assert "bull" in body["scenarios"]
        assert "base" in body["scenarios"]
        assert "bear" in body["scenarios"]

    def test_probabilities_normalized_to_one(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)
        _seed_market(tmp_db, today)

        # Kasıtlı olarak toplamı 1'i geçen olasılıklar ver
        skewed = {
            "scenarios": {
                "bull": {"probability": 0.4, "description": "x", "stocks": []},
                "base": {"probability": 0.4, "description": "x", "stocks": []},
                "bear": {"probability": 0.4, "description": "x", "stocks": []},
            },
            "time_horizon": "hafta",
            "key_risk": "r",
            "key_opportunity": "o",
        }
        agent = AnalystAgent(llm_client=_mock_llm(skewed))
        content_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT body FROM content WHERE id=?", (content_ids[0],))
        body = json.loads(row["body"])
        total = sum(s["probability"] for s in body["scenarios"].values())
        assert abs(total - 1.0) < 0.01

    def test_trigger_condition_active_flag(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today, rule_ids=["fed_hawkish"])
        # ^TNX change_pct=0.08 > 0.05 → koşul aktif
        _seed_market(tmp_db, today, ticker="^TNX", change_pct=0.08)

        agent = AnalystAgent(llm_client=_mock_llm())
        content_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT body FROM content WHERE id=?", (content_ids[0],))
        body = json.loads(row["body"])
        assert body["trigger_conditions_active"] is True

    def test_budget_exceeded_stops_loop(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)
        _seed_signal(tmp_db, today)

        budget_llm = MagicMock()
        budget_llm.call.side_effect = BudgetExceeded("aylık limit")

        agent = AnalystAgent(llm_client=budget_llm)
        content_ids = agent.run(date.today())

        assert content_ids == []

    def test_returns_empty_when_no_signals(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        agent = AnalystAgent(llm_client=_mock_llm())
        content_ids = agent.run(date.today())

        assert content_ids == []
        _mock_llm().call.assert_not_called()

    def test_json_error_skips_signal(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        bad_llm = MagicMock()
        bad_llm.call.return_value = LLMResponse(
            content="Bu JSON değil dostum",
            input_tokens=10, output_tokens=5, total_tokens=15,
            cost_usd=0.0, duration_ms=100,
        )

        agent = AnalystAgent(llm_client=bad_llm)
        content_ids = agent.run(date.today())

        assert content_ids == []

    def test_body_contains_signal_id(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        signal_id = _seed_signal(tmp_db, today)
        _seed_market(tmp_db, today)

        agent = AnalystAgent(llm_client=_mock_llm())
        content_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT body FROM content WHERE id=?", (content_ids[0],))
        body = json.loads(row["body"])
        assert body["signal_id"] == signal_id
