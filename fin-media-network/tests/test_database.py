"""Gün 1 testi: DB init ve temel CRUD."""
import json
import tempfile
from pathlib import Path

import pytest

from src.db.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.init()
    return d


def test_init_creates_tables(db):
    tables = db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r["name"] for r in tables}
    expected = {"raw_news", "clusters", "market_snapshots", "signals", "content", "performance", "prompt_versions", "llm_calls"}
    assert expected.issubset(names)


def test_insert_raw_news(db):
    rows = [
        {
            "url_hash": "abc123",
            "url": "https://example.com/news/1",
            "title": "Test haber başlığı",
            "summary": "Özet metin",
            "source_name": "example.com",
            "source_url": "https://example.com",
            "published_at": "2026-06-11 06:00:00",
            "feed_name": "test_feed",
            "raw_json": json.dumps({"key": "value"}),
        }
    ]
    count = db.insert_raw_news(rows)
    assert count == 1

    result = db.fetchone("SELECT * FROM raw_news WHERE url_hash=?", ("abc123",))
    assert result["title"] == "Test haber başlığı"
    assert result["source_name"] == "example.com"


def test_insert_raw_news_ignores_duplicate(db):
    row = {
        "url_hash": "dup001",
        "url": "https://example.com/dup",
        "title": "Duplicate",
        "summary": None,
        "source_name": "test",
        "source_url": None,
        "published_at": None,
        "feed_name": "test",
        "raw_json": None,
    }
    db.insert_raw_news([row])
    db.insert_raw_news([row])  # aynı url_hash → IGNORE
    result = db.fetchall("SELECT * FROM raw_news WHERE url_hash='dup001'")
    assert len(result) == 1


def test_insert_market_snapshot(db):
    db.insert_market_snapshot({
        "date": "2026-06-11",
        "ticker": "XU100.IS",
        "open": 9500.0,
        "high": 9600.0,
        "low": 9450.0,
        "close": 9580.0,
        "volume": 1234567890.0,
        "change_pct": 0.84,
        "source": "yfinance",
        "extra_json": None,
    })
    row = db.fetchone("SELECT * FROM market_snapshots WHERE ticker=?", ("XU100.IS",))
    assert row["close"] == 9580.0
    assert row["source"] == "yfinance"


def test_insert_cluster_and_signal(db):
    cluster_id = db.insert_cluster({
        "date": "2026-06-11",
        "representative_title": "Fed faiz kararı piyasaları sarstı",
        "news_count": 3,
        "source_weight": 0.9,
        "market_relevance": 0.8,
        "volatility_impact": 1.0,
        "score": 82.0,
        "tier": 1,
        "keywords": json.dumps(["Fed", "faiz", "hawkish"]),
        "tickers_mentioned": json.dumps(["^TNX", "DX-Y.NYB"]),
    })
    assert cluster_id > 0

    signal_id = db.insert_signal({
        "date": "2026-06-11",
        "cluster_id": cluster_id,
        "headline": "Fed şahin tutumla faizi sabit tuttu",
        "what_happened": "FOMC toplantısında faiz değişmedi fakat açıklamalar sıkılaştırıcı çıktı.",
        "why_it_matters": "TRY üzerinde baskı artacak, BIST riskli.",
        "bias": "bearish",
        "confidence": 0.8,
        "transmission_rule_ids": json.dumps(["fed_hawkish"]),
        "bist_impact_json": json.dumps({"impact": "negatif", "sectors": ["bankacılık"]}),
        "rank": 1,
    })
    assert signal_id > 0


def test_log_llm_call_and_cost(db):
    db.log_llm_call({
        "agent": "research",
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": 2000,
        "output_tokens": 1000,
        "total_tokens": 3000,
        "cost_usd": 0.0009,
        "duration_ms": 1200,
        "success": 1,
        "error_message": None,
    })
    from datetime import date
    cost = db.get_daily_llm_cost(date.today().isoformat())
    assert cost > 0.0


def test_double_init_is_idempotent(db):
    db.init()  # ikinci init tablolar silinmemeli
    tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    assert len(tables) >= 8
