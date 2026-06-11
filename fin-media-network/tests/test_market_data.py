"""Gün 2 testi: market_data, macro_data, crypto_data — API'siz fixture'larla."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ── market_data testleri ──────────────────────────────────────────────────────

from src.ingestion.market_data import (
    fetch_ticker,
    save_to_db,
)


@pytest.fixture
def fake_hist_df():
    """2 günlük sahte OHLCV DataFrame."""
    idx = pd.to_datetime(["2026-06-10", "2026-06-11"])
    return pd.DataFrame(
        {
            "Open":   [9400.0, 9450.0],
            "High":   [9500.0, 9612.0],
            "Low":    [9380.0, 9420.0],
            "Close":  [9450.0, 9580.0],
            "Volume": [10e9,   14e9],
        },
        index=idx,
    )


def test_fetch_ticker_yfinance(fake_hist_df, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    # settings.yaml asgari kopya
    import yaml
    (tmp_path / "config" / "settings.yaml").write_text(yaml.dump({"tickers": {}}))

    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = fake_hist_df
        result = fetch_ticker("XU100.IS", use_cache=False)

    assert result is not None
    assert result["ticker"] == "XU100.IS"
    assert result["close"] == 9580.0
    assert result["source"] == "yfinance"
    assert abs(result["change_pct"] - ((9580 - 9450) / 9450 * 100)) < 0.01


def test_fetch_ticker_stooq_fallback(tmp_path, monkeypatch):
    """yfinance boş dönünce Stooq fallback devreye girer."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    import yaml
    (tmp_path / "config" / "settings.yaml").write_text(yaml.dump({"tickers": {}}))

    # Stooq CSV formatı: Date sütunu + OHLCV
    stooq_df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-06-10", "2026-06-11"]),
        "Open":   [9400.0, 9450.0],
        "High":   [9500.0, 9612.0],
        "Low":    [9380.0, 9420.0],
        "Close":  [9450.0, 9580.0],
        "Volume": [10e9,   14e9],
    })

    with patch("yfinance.Ticker") as mock_yf, \
         patch("pandas.read_csv", return_value=stooq_df):
        mock_yf.return_value.history.return_value = pd.DataFrame()  # boş
        result = fetch_ticker("XU100.IS", use_cache=False)

    assert result is not None
    assert result["close"] == 9580.0
    assert result["source"] == "stooq"


def test_fetch_ticker_returns_none_on_total_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    import yaml
    (tmp_path / "config" / "settings.yaml").write_text(yaml.dump({"tickers": {}}))

    with patch("yfinance.Ticker") as mock_yf, \
         patch("pandas.read_csv", side_effect=Exception("ağ hatası")):
        mock_yf.return_value.history.return_value = pd.DataFrame()
        result = fetch_ticker("NONEXIST.XX", use_cache=False)

    assert result is None


def test_save_to_db(tmp_path):
    from src.db.database import reset_db
    db = reset_db(tmp_path / "test.db")
    db.init()

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "market_snapshot_yfinance.json").read_text()
    )
    fixture["extra_json"] = None
    count = save_to_db([fixture])
    assert count == 1

    rows = db.fetchall("SELECT * FROM market_snapshots WHERE ticker=?", ("XU100.IS",))
    assert len(rows) == 1
    assert rows[0]["close"] == 9580.1


# ── crypto_data testleri ──────────────────────────────────────────────────────

from src.ingestion.crypto_data import fetch_prices, fetch_global_dominance


def test_fetch_prices_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    import yaml
    (tmp_path / "config" / "settings.yaml").write_text(
        yaml.dump({"crypto": {"coins": ["bitcoin", "ethereum"], "vs_currency": "usd"}})
    )

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "coingecko_simple_price.json").read_text()
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        results = fetch_prices(["bitcoin", "ethereum"])

    assert len(results) == 2
    btc = next(r for r in results if r["ticker"] == "bitcoin")
    assert btc["close"] == 67543.21
    assert btc["change_pct"] == 2.34
    assert btc["source"] == "coingecko"


def test_fetch_global_dominance_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "coingecko_global.json").read_text()
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        result = fetch_global_dominance()

    assert result is not None
    assert result["ticker"] == "crypto_global"
    assert result["close"] == 54.32


def test_fetch_prices_network_error_returns_empty(tmp_path, monkeypatch):
    import requests as req
    monkeypatch.chdir(tmp_path)
    with patch("requests.get", side_effect=req.RequestException("timeout")):
        results = fetch_prices(["bitcoin"])
    assert results == []


# ── macro_data testleri ───────────────────────────────────────────────────────

from src.ingestion.macro_data import _fetch_fred_series


def test_fetch_fred_series_mock(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "testkey123")
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "fred_fedfunds.json").read_text()
    )
    mock_resp = MagicMock()
    mock_resp.json.return_value = fixture
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp):
        result = _fetch_fred_series("FEDFUNDS", "testkey123")

    assert result is not None
    assert result["ticker"] == "FEDFUNDS"
    assert result["close"] == 5.33
    assert result["source"] == "fred"


def test_fetch_fred_no_key_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    import yaml
    (tmp_path / "config" / "settings.yaml").write_text(
        yaml.dump({"fred": {"series": {"FEDFUNDS": "Fed Funds Rate"}}})
    )
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from src.ingestion.macro_data import fetch_fred_all
    result = fetch_fred_all()
    assert result == []


def test_fetch_fred_network_error(monkeypatch):
    import requests as req
    with patch("requests.get", side_effect=req.RequestException("DNS")):
        result = _fetch_fred_series("FEDFUNDS", "somekey")
    assert result is None
