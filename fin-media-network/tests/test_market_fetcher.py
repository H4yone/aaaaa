"""
MarketFetcher testleri — yfinance, fredapi ve requests mocklıdır.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import yaml

from src.db.database import reset_db
from src.ingestion.market_fetcher import MarketFetcher


# ── Yardımcı sabitler ────────────────────────────────────────────────────────

_SETTINGS = {
    "pipeline": {"daily_run_hour": 6, "timezone": "UTC"},
    "tickers": {
        "bist": {
            "indices": ["XU100.IS"],
            "stocks": [],
        },
        "global": {
            "indices": [],
            "fx": [],
            "bonds": [],
            "commodities": [],
            "tech": [],
        },
    },
    "crypto": {
        "coins": ["bitcoin"],
        "vs_currency": "usd",
    },
    "fred": {
        "series": {
            "FEDFUNDS": "Fed Funds Rate",
        }
    },
}


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Geçici settings.yaml dosyası oluşturur."""
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.dump(_SETTINGS), encoding="utf-8")
    return p


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch):
    """Test veritabanını sıfırlar ve başlatır."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    db = reset_db(db_path)
    db.init()
    return db


def _mock_yf_module(tickers: list[str] | None = None, close_values: list[float] | None = None) -> MagicMock:
    """Belirli bir Close serisi dönen yfinance mock'u oluşturur."""
    if tickers is None:
        tickers = ["XU100.IS"]
    if close_values is None:
        close_values = [9500.0, 9600.0]

    mock = MagicMock()
    # Tek ticker için doğrudan sütun yapısı
    df = pd.DataFrame({
        "Close": close_values,
        "Open": [v - 50 for v in close_values],
        "High": [v + 100 for v in close_values],
        "Low": [v - 100 for v in close_values],
        "Volume": [1_000_000] * len(close_values),
    })
    mock.download.return_value = df
    return mock


def _mock_fred_client(value: float = 5.25) -> MagicMock:
    """Sabit bir değer dönen FRED istemcisi mock'u oluşturur."""
    fred = MagicMock()
    fred.get_series.return_value = pd.Series(
        [value], index=[pd.Timestamp("2026-06-12")]
    )
    return fred


def _mock_cg_session(coin: str = "bitcoin", price: float = 50_000.0, change: float = 3.5) -> MagicMock:
    """CoinGecko fiyat endpoint'ini taklit eden requests.Session mock'u oluşturur."""
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {coin: {"usd": price, "usd_24h_change": change}}
    resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


# ── TestFetchYfinance ─────────────────────────────────────────────────────────

class TestFetchYfinance:
    def test_returns_list_of_dicts(self, config_file: Path):
        """yfinance verileri işlendiğinde dict listesi döner."""
        yf = _mock_yf_module()
        fetcher = MarketFetcher(config_path=config_file, yf_module=yf)
        result = fetcher._fetch_yfinance(["XU100.IS"], "2026-06-12")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_required_keys_present(self, config_file: Path):
        """Her dict zorunlu alan anahtarlarını içerir."""
        yf = _mock_yf_module()
        fetcher = MarketFetcher(config_path=config_file, yf_module=yf)
        row = fetcher._fetch_yfinance(["XU100.IS"], "2026-06-12")[0]
        for key in ("date", "ticker", "open", "high", "low", "close", "volume", "change_pct", "source"):
            assert key in row, f"Eksik anahtar: {key}"

    def test_source_is_yfinance(self, config_file: Path):
        """Kaynak 'yfinance' olarak işaretlenir."""
        yf = _mock_yf_module()
        fetcher = MarketFetcher(config_path=config_file, yf_module=yf)
        row = fetcher._fetch_yfinance(["XU100.IS"], "2026-06-12")[0]
        assert row["source"] == "yfinance"

    def test_change_pct_calculated(self, config_file: Path):
        """İki kapanış fiyatından değişim yüzdesi hesaplanır."""
        # İki günlük kapanış: 9500 → 9600 → %1.05 artış
        yf = _mock_yf_module(close_values=[9500.0, 9600.0])
        fetcher = MarketFetcher(config_path=config_file, yf_module=yf)
        row = fetcher._fetch_yfinance(["XU100.IS"], "2026-06-12")[0]
        expected = (9600.0 - 9500.0) / 9500.0 * 100
        assert abs(row["change_pct"] - expected) < 0.01

    def test_empty_list_for_empty_tickers(self, config_file: Path):
        """Ticker listesi boşsa boş liste döner."""
        fetcher = MarketFetcher(config_path=config_file, yf_module=MagicMock())
        result = fetcher._fetch_yfinance([], "2026-06-12")
        assert result == []


# ── TestFetchFred ─────────────────────────────────────────────────────────────

class TestFetchFred:
    def test_returns_dict_with_fred_source(self, config_file: Path):
        """FRED verisi işlendiğinde source='fred' olan dict döner."""
        fred = _mock_fred_client(5.25)
        fetcher = MarketFetcher(config_path=config_file, fred_client=fred)
        result = fetcher._fetch_fred({"FEDFUNDS": "Fed Funds Rate"}, "2026-06-12")
        assert len(result) == 1
        assert result[0]["source"] == "fred"

    def test_close_value_matches_series(self, config_file: Path):
        """close alanı, FRED serisindeki son değere eşit olur."""
        fred = _mock_fred_client(5.25)
        fetcher = MarketFetcher(config_path=config_file, fred_client=fred)
        result = fetcher._fetch_fred({"FEDFUNDS": "Fed Funds Rate"}, "2026-06-12")
        assert result[0]["close"] == 5.25

    def test_empty_series_skipped(self, config_file: Path):
        """Boş FRED serisi atlanır, sonuç listesi boş döner."""
        fred = MagicMock()
        fred.get_series.return_value = pd.Series([], dtype=float)
        fetcher = MarketFetcher(config_path=config_file, fred_client=fred)
        result = fetcher._fetch_fred({"FEDFUNDS": "Fed Funds Rate"}, "2026-06-12")
        assert result == []


# ── TestFetchCoingecko ────────────────────────────────────────────────────────

class TestFetchCoingecko:
    def test_returns_bitcoin_dict(self, config_file: Path):
        """Bitcoin fiyatı başarıyla ayrıştırılır."""
        cg = _mock_cg_session("bitcoin", 50_000.0, 3.5)
        fetcher = MarketFetcher(config_path=config_file, cg_session=cg)
        result = fetcher._fetch_coingecko(["bitcoin"], "usd", "2026-06-12")
        assert len(result) == 1
        assert result[0]["ticker"] == "bitcoin"

    def test_change_pct_matches_api_response(self, config_file: Path):
        """change_pct, API'den gelen 24 saatlik değişime eşit olur."""
        cg = _mock_cg_session("bitcoin", 50_000.0, 3.5)
        fetcher = MarketFetcher(config_path=config_file, cg_session=cg)
        result = fetcher._fetch_coingecko(["bitcoin"], "usd", "2026-06-12")
        assert result[0]["change_pct"] == 3.5

    def test_close_matches_price(self, config_file: Path):
        """close alanı API'den gelen fiyata eşit olur."""
        cg = _mock_cg_session("bitcoin", 50_000.0, 3.5)
        fetcher = MarketFetcher(config_path=config_file, cg_session=cg)
        result = fetcher._fetch_coingecko(["bitcoin"], "usd", "2026-06-12")
        assert result[0]["close"] == 50_000.0

    def test_empty_coins_returns_empty(self, config_file: Path):
        """Coin listesi boşsa boş liste döner."""
        fetcher = MarketFetcher(config_path=config_file, cg_session=MagicMock())
        result = fetcher._fetch_coingecko([], "usd", "2026-06-12")
        assert result == []


# ── TestMarketFetcherRun ──────────────────────────────────────────────────────

class TestMarketFetcherRun:
    def test_returns_tickers_fetched(self, config_file: Path, tmp_db, monkeypatch):
        """run() çağrısı sonucunda çekilen ticker adları liste olarak döner."""
        yf = _mock_yf_module(["XU100.IS"])
        fred = _mock_fred_client(5.25)
        cg = _mock_cg_session("bitcoin", 50_000.0, 2.0)
        fetcher = MarketFetcher(
            config_path=config_file,
            yf_module=yf,
            fred_client=fred,
            cg_session=cg,
        )
        result = fetcher.run("2026-06-12")
        assert isinstance(result, list)
        # En az 1 ticker dönmelidir
        assert len(result) >= 1

    def test_yfinance_error_skips_gracefully(self, config_file: Path, tmp_db, monkeypatch):
        """yfinance hata fırlatırsa FRED/CoinGecko verileri yine de işlenir."""
        yf = MagicMock()
        yf.download.side_effect = Exception("Ağ hatası")
        fred = _mock_fred_client(5.25)
        cg = _mock_cg_session("bitcoin", 50_000.0, 2.0)
        fetcher = MarketFetcher(
            config_path=config_file,
            yf_module=yf,
            fred_client=fred,
            cg_session=cg,
        )
        result = fetcher.run("2026-06-12")
        # FRED ve CoinGecko'dan veri gelmiş olmalı
        assert "FEDFUNDS" in result or "bitcoin" in result

    def test_inserts_to_db(self, config_file: Path, tmp_db, monkeypatch):
        """run() sonrası market_snapshots tablosuna satır eklenmiş olmalı."""
        yf = _mock_yf_module(["XU100.IS"])
        fred = _mock_fred_client(5.25)
        cg = _mock_cg_session("bitcoin", 50_000.0, 2.0)
        fetcher = MarketFetcher(
            config_path=config_file,
            yf_module=yf,
            fred_client=fred,
            cg_session=cg,
        )
        fetcher.run("2026-06-12")
        rows = tmp_db.fetchall(
            "SELECT * FROM market_snapshots WHERE date=?", ("2026-06-12",)
        )
        assert len(rows) >= 1
