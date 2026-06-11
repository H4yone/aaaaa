"""
ResearchAgent testleri — LLM ve DB mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import reset_db
from src.intelligence.llm_client import BudgetExceeded, LLMResponse
from src.intelligence.research_agent import ResearchAgent


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.call.return_value = LLMResponse(
        content=json.dumps({
            "headline": "Fed faizi artırdı, BIST baskı altında",
            "what_happened": "Fed 25 baz puan faiz artışı yaptı.",
            "why_it_matters": "EM'den fon çıkışı BIST'i baskılar.",
            "bias": "bearish",
            "confidence": 0.82,
            "bist_impact": {
                "overall": "negatif",
                "sectors": [
                    {
                        "sector": "bankacılık",
                        "stocks": ["GARAN.IS"],
                        "direction": "aşağı",
                        "reasoning": "Sermaye çıkışı",
                    }
                ],
            },
        }),
        input_tokens=500,
        output_tokens=150,
        total_tokens=650,
        cost_usd=0.001,
        duration_ms=800,
    )
    return llm


def _seed_cluster(db, date_str: str, tier: int = 1, score: float = 80.0) -> int:
    return db.insert_cluster({
        "date": date_str,
        "representative_title": "Fed hawkish, faiz artışı beklentisi güçlendi",
        "news_count": 5,
        "source_weight": 0.9,
        "market_relevance": 0.8,
        "volatility_impact": 0.7,
        "score": score,
        "tier": tier,
        "keywords": json.dumps(["hawkish", "rate hike", "Fed"]),
        "tickers_mentioned": json.dumps(["^TNX"]),
    })


def _seed_market(db, date_str: str) -> None:
    db.insert_market_snapshot({
        "date": date_str,
        "ticker": "XU100.IS",
        "open": 10000.0,
        "high": 10100.0,
        "low": 9900.0,
        "close": 9950.0,
        "volume": 1_000_000.0,
        "change_pct": -0.5,
        "source": "yfinance",
        "extra_json": None,
    })


# ── Kural eşleştirme ──────────────────────────────────────────────────────────

class TestMatchRules:
    def test_matches_fed_hawkish(self, tmp_db):
        agent = ResearchAgent(llm_client=MagicMock())
        rules = agent._match_rules(["hawkish", "rate hike"], "Fed hawkish kararı")
        ids = [r["id"] for r in rules]
        assert "fed_hawkish" in ids

    def test_no_match_for_unrelated(self, tmp_db):
        agent = ResearchAgent(llm_client=MagicMock())
        rules = agent._match_rules(["hava", "bulut"], "Bugün hava güzel")
        assert rules == []

    def test_case_insensitive(self, tmp_db):
        agent = ResearchAgent(llm_client=MagicMock())
        rules = agent._match_rules(["NASDAQ", "RALLY"], "Piyasa haberi")
        ids = [r["id"] for r in rules]
        assert "nasdaq_rally" in ids


# ── JSON ayrıştırma ───────────────────────────────────────────────────────────

class TestParseJson:
    def test_plain_json(self):
        raw = '{"headline": "Test", "bias": "bullish", "confidence": 0.9}'
        result = ResearchAgent._parse_json(raw)
        assert result["headline"] == "Test"

    def test_markdown_code_block(self):
        raw = '```json\n{"headline": "Test2", "bias": "bearish"}\n```'
        result = ResearchAgent._parse_json(raw)
        assert result["bias"] == "bearish"

    def test_json_with_surrounding_text(self):
        raw = 'İşte analiz:\n{"headline": "X", "confidence": 0.7}\nTeşekkürler'
        result = ResearchAgent._parse_json(raw)
        assert result["confidence"] == 0.7

    def test_raises_on_invalid(self):
        import json as _json
        with pytest.raises(_json.JSONDecodeError):
            ResearchAgent._parse_json("Bu geçerli JSON değil.")


# ── Tam çalışma döngüsü ───────────────────────────────────────────────────────

class TestResearchAgentRun:
    def test_creates_signal_for_tier1_cluster(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cluster_id = _seed_cluster(tmp_db, today, tier=1)
        _seed_market(tmp_db, today)

        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        assert len(signal_ids) == 1
        row = tmp_db.fetchone("SELECT * FROM signals WHERE id=?", (signal_ids[0],))
        assert row is not None
        assert row["cluster_id"] == cluster_id
        assert row["bias"] == "bearish"
        assert abs(row["confidence"] - 0.82) < 0.001
        assert row["rank"] == 1

    def test_creates_signals_ordered_by_score(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_cluster(tmp_db, today, tier=1, score=60.0)
        _seed_cluster(tmp_db, today, tier=2, score=80.0)
        _seed_market(tmp_db, today)

        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        assert len(signal_ids) == 2
        # İlk sinyal en yüksek skorlu kümeye ait olmalı (rank=1)
        first = tmp_db.fetchone("SELECT * FROM signals WHERE rank=1")
        assert first is not None

    def test_skips_tier3_clusters(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        # Tier yoksa NULL → tier IN (1,2) sorgusu bunu getirmez
        tmp_db.insert_cluster({
            "date": today,
            "representative_title": "Önemsiz haber",
            "news_count": 1,
            "source_weight": 0.4,
            "market_relevance": 0.1,
            "volatility_impact": 0.1,
            "score": 20.0,
            "tier": None,
            "keywords": json.dumps([]),
            "tickers_mentioned": json.dumps([]),
        })

        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        assert signal_ids == []
        mock_llm.call.assert_not_called()

    def test_budget_exceeded_stops_loop(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_cluster(tmp_db, today, tier=1, score=90.0)
        _seed_cluster(tmp_db, today, tier=1, score=85.0)

        budget_llm = MagicMock()
        budget_llm.call.side_effect = BudgetExceeded("günlük limit")

        agent = ResearchAgent(llm_client=budget_llm)
        signal_ids = agent.run(date.today())

        # BudgetExceeded → döngü kırılır, hiç sinyal yazılmaz
        assert signal_ids == []

    def test_json_error_skips_cluster(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_cluster(tmp_db, today, tier=1, score=80.0)

        bad_llm = MagicMock()
        bad_llm.call.return_value = LLMResponse(
            content="Bu JSON değil",
            input_tokens=10, output_tokens=5, total_tokens=15,
            cost_usd=0.0, duration_ms=100,
        )

        agent = ResearchAgent(llm_client=bad_llm)
        signal_ids = agent.run(date.today())

        # parse hatası → sinyal yazılmaz
        assert signal_ids == []

    def test_returns_empty_when_no_clusters(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        assert signal_ids == []
        mock_llm.call.assert_not_called()

    def test_transmission_rule_ids_stored(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_cluster(tmp_db, today, tier=1)

        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT transmission_rule_ids FROM signals WHERE id=?", (signal_ids[0],))
        rule_ids = json.loads(row["transmission_rule_ids"])
        # "hawkish" ve "rate hike" → fed_hawkish kuralıyla eşleşmeli
        assert "fed_hawkish" in rule_ids

    def test_bist_impact_json_stored(self, tmp_db, mock_llm, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_cluster(tmp_db, today, tier=1)

        agent = ResearchAgent(llm_client=mock_llm)
        signal_ids = agent.run(date.today())

        row = tmp_db.fetchone("SELECT bist_impact_json FROM signals WHERE id=?", (signal_ids[0],))
        impact = json.loads(row["bist_impact_json"])
        assert impact["overall"] == "negatif"
        assert len(impact["sectors"]) == 1
