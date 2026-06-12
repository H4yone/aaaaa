from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from src.db.database import get_db

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"


class MarketFetcher:
    def __init__(
        self,
        config_path: str | Path | None = None,
        yf_module: Any | None = None,
        fred_client: Any | None = None,
        cg_session: Any | None = None,
    ) -> None:
        self._cfg_path = Path(config_path) if config_path else _CONFIG_PATH
        self._yf = yf_module
        self._fred = fred_client
        self._cg = cg_session

        # Ayarları yükle
        with open(self._cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        tickers = cfg.get("tickers", {})
        bist = tickers.get("bist", {})
        glb = tickers.get("global", {})
        crypto_cfg = cfg.get("crypto", {})
        fred_cfg = cfg.get("fred", {})

        self._bist_indices: list[str] = bist.get("indices", [])
        self._bist_stocks: list[str] = bist.get("stocks", [])
        self._global_indices: list[str] = glb.get("indices", [])
        self._global_fx: list[str] = glb.get("fx", [])
        self._global_bonds: list[str] = glb.get("bonds", [])
        self._global_commodities: list[str] = glb.get("commodities", [])
        self._global_tech: list[str] = glb.get("tech", [])
        self._crypto_coins: list[str] = crypto_cfg.get("coins", [])
        self._crypto_vs: str = crypto_cfg.get("vs_currency", "usd")
        self._fred_series: dict[str, str] = fred_cfg.get("series", {})

    def _get_yf(self) -> Any:
        # yfinance modülünü tembel yükle
        if self._yf is None:
            import yfinance as yf
            self._yf = yf
        return self._yf

    def _get_fred(self) -> Any:
        # fredapi istemcisini tembel yükle
        if self._fred is None:
            from fredapi import Fred
            self._fred = Fred(api_key=os.getenv("FRED_API_KEY", ""))
        return self._fred

    def _get_cg(self) -> Any:
        # requests.Session'ı tembel yükle
        if self._cg is None:
            import requests
            self._cg = requests.Session()
        return self._cg

    def _fetch_yfinance(self, tickers: list[str], date_str: str) -> list[dict]:
        if not tickers:
            return []

        try:
            df = self._get_yf().download(
                tickers,
                period="2d",
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            logger.warning("[MarketFetcher] yfinance indirme hatası: %s", exc)
            return []

        if df is None or df.empty:
            return []

        rows: list[dict] = []

        # Tek ticker durumunda sütun yapısı farklı; normalize et
        single = isinstance(tickers, str) or len(tickers) == 1
        ticker_list = [tickers] if isinstance(tickers, str) else tickers

        for ticker in ticker_list:
            try:
                if single or len(ticker_list) == 1:
                    # Tek ticker: sütunlar doğrudan Open/High/Low/Close/Volume
                    t_df = df
                else:
                    # Çoklu ticker: MultiIndex sütun yapısı
                    t_df = df.xs(ticker, axis=1, level=1) if ("Close", ticker) in df.columns else df[ticker] if ticker in df.columns else None  # type: ignore[assignment]

                if t_df is None or t_df.empty:
                    continue

                # Son iki satırı al
                closes = t_df["Close"].dropna()
                if closes.empty:
                    continue

                last_row = t_df.iloc[-1]
                open_val = float(last_row.get("Open", 0) or 0)
                high_val = float(last_row.get("High", 0) or 0)
                low_val = float(last_row.get("Low", 0) or 0)
                close_val = float(closes.iloc[-1])
                volume_val = float(last_row.get("Volume", 0) or 0)

                if len(closes) >= 2:
                    prev_close = float(closes.iloc[-2])
                    change_pct = (close_val - prev_close) / prev_close * 100 if prev_close else 0.0
                else:
                    change_pct = 0.0

                rows.append({
                    "date": date_str,
                    "ticker": ticker,
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "close": close_val,
                    "volume": volume_val,
                    "change_pct": change_pct,
                    "source": "yfinance",
                    "extra_json": None,
                })
            except Exception as exc:
                logger.warning("[MarketFetcher] %s işlenirken hata: %s", ticker, exc)
                continue

        return rows

    def _fetch_fred(self, series_dict: dict[str, str], date_str: str) -> list[dict]:
        rows: list[dict] = []
        fred = self._get_fred()

        for series_id, _name in series_dict.items():
            try:
                series = fred.get_series(
                    series_id,
                    observation_start=date_str,
                    observation_end=date_str,
                )
                if series is None or series.empty:
                    continue

                close_val = float(series.iloc[-1])
                rows.append({
                    "date": date_str,
                    "ticker": series_id,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": close_val,
                    "volume": None,
                    "change_pct": None,
                    "source": "fred",
                    "extra_json": None,
                })
            except Exception as exc:
                logger.warning("[MarketFetcher] FRED %s hatası: %s", series_id, exc)
                continue

        return rows

    def _fetch_coingecko(self, coins: list[str], vs_currency: str, date_str: str) -> list[dict]:
        if not coins:
            return []

        try:
            resp = self._get_cg().get(
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={','.join(coins)}&vs_currencies={vs_currency}&include_24hr_change=true",
                timeout=30,
            )
            resp.raise_for_status()
            data: dict = resp.json()
        except Exception as exc:
            logger.warning("[MarketFetcher] CoinGecko hatası: %s", exc)
            return []

        rows: list[dict] = []
        for coin in coins:
            try:
                coin_data = data.get(coin, {})
                if not coin_data:
                    continue
                price = float(coin_data.get(vs_currency, 0))
                change_pct = coin_data.get(f"{vs_currency}_24h_change")
                if change_pct is not None:
                    change_pct = float(change_pct)
                rows.append({
                    "date": date_str,
                    "ticker": coin,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": price,
                    "volume": None,
                    "change_pct": change_pct,
                    "source": "coingecko",
                    "extra_json": None,
                })
            except Exception as exc:
                logger.warning("[MarketFetcher] %s coin işlenirken hata: %s", coin, exc)
                continue

        return rows

    def run(self, run_date: str | None = None) -> list[str]:
        date_str = run_date or date.today().isoformat()
        db = get_db()

        # Tüm yfinance ticker'larını bir arada indir
        all_yf_tickers: list[str] = (
            self._bist_indices
            + self._bist_stocks
            + self._global_indices
            + self._global_fx
            + self._global_bonds
            + self._global_commodities
            + self._global_tech
        )

        yf_rows = self._fetch_yfinance(all_yf_tickers, date_str)
        fred_rows = self._fetch_fred(self._fred_series, date_str)
        cg_rows = self._fetch_coingecko(self._crypto_coins, self._crypto_vs, date_str)

        all_rows = yf_rows + fred_rows + cg_rows

        fetched_tickers: list[str] = []
        for row in all_rows:
            try:
                db.insert_market_snapshot(row)
                fetched_tickers.append(row["ticker"])
            except Exception as exc:
                logger.warning(
                    "[MarketFetcher] %s snapshot ekleme hatası: %s",
                    row.get("ticker"),
                    exc,
                )

        logger.info(
            "[MarketFetcher] %s: %d snapshot eklendi",
            date_str,
            len(fetched_tickers),
        )
        return fetched_tickers
