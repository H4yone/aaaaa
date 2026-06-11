"""
LAYER 1 — Market data ingestion
yfinance (birincil) + Stooq CSV (fallback) + 15 dk disk cache
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
import yaml

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("cache/market")
_CACHE_TTL_SECONDS = 900  # 15 dakika


def _load_settings() -> dict:
    path = Path("config/settings.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cache_path(ticker: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{ticker.replace('/', '_').replace('^', 'IDX_')}.json"


def _read_cache(ticker: str) -> Optional[dict]:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > _CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data), encoding="utf-8")


def _fetch_yfinance(ticker: str, period: str = "2d") -> Optional[dict]:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=True)
        if hist.empty:
            return None
        row = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else row
        close = float(row["Close"])
        prev_close = float(prev["Close"])
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
        return {
            "ticker": ticker,
            "date": str(hist.index[-1].date()),
            "open": float(row["Open"]) if not pd.isna(row["Open"]) else None,
            "high": float(row["High"]) if not pd.isna(row["High"]) else None,
            "low": float(row["Low"]) if not pd.isna(row["Low"]) else None,
            "close": close,
            "volume": float(row["Volume"]) if not pd.isna(row["Volume"]) else None,
            "change_pct": round(change_pct, 4),
            "source": "yfinance",
        }
    except Exception as e:
        logger.warning("yfinance hata [%s]: %s", ticker, e)
        return None


def _fetch_stooq(ticker: str) -> Optional[dict]:
    """
    Stooq CSV fallback — yfinance başarısız olduğunda kullanılır.
    Stooq ticker formatı yfinance'den farklı olabilir (örn. ^SPX → SPX).
    """
    # Basit ticker dönüşümü
    stooq_ticker = (
        ticker.replace("^", "")
              .replace(".IS", ".IS")   # BIST hisseler .IS ekini korur
              .upper()
    )
    url = f"https://stooq.com/q/d/l/?s={stooq_ticker}&i=d"
    try:
        df = pd.read_csv(url)
        if df.empty or "Close" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date")
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else row
        close = float(row["Close"])
        prev_close = float(prev["Close"])
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
        return {
            "ticker": ticker,
            "date": str(row["Date"].date()),
            "open": float(row["Open"]) if "Open" in row and not pd.isna(row["Open"]) else None,
            "high": float(row["High"]) if "High" in row and not pd.isna(row["High"]) else None,
            "low": float(row["Low"]) if "Low" in row and not pd.isna(row["Low"]) else None,
            "close": close,
            "volume": float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else None,
            "change_pct": round(change_pct, 4),
            "source": "stooq",
        }
    except Exception as e:
        logger.warning("Stooq hata [%s]: %s", ticker, e)
        return None


def fetch_ticker(ticker: str, use_cache: bool = True) -> Optional[dict]:
    """Tek ticker için OHLCV verisi — önce cache, sonra yfinance, sonra Stooq."""
    if use_cache:
        cached = _read_cache(ticker)
        if cached:
            logger.debug("Cache hit: %s", ticker)
            return cached

    data = _fetch_yfinance(ticker)
    if data is None:
        logger.info("yfinance başarısız, Stooq fallback: %s", ticker)
        data = _fetch_stooq(ticker)

    if data:
        _write_cache(ticker, data)
    else:
        logger.error("Veri alınamadı: %s", ticker)

    return data


def fetch_all_tickers(use_cache: bool = True) -> list[dict]:
    """settings.yaml'daki tüm ticker'ları çeker."""
    settings = _load_settings()
    tickers_cfg = settings.get("tickers", {})

    all_tickers: list[str] = []
    for group in tickers_cfg.get("bist", {}).values():
        all_tickers.extend(group)
    for group in tickers_cfg.get("global", {}).values():
        all_tickers.extend(group)

    results: list[dict] = []
    for ticker in all_tickers:
        data = fetch_ticker(ticker, use_cache=use_cache)
        if data:
            results.append(data)
        time.sleep(0.1)   # rate limit nezaketi

    logger.info("Toplam %d/%d ticker çekildi", len(results), len(all_tickers))
    return results


def save_to_db(snapshots: list[dict]) -> int:
    """Snapshot listesini market_snapshots tablosuna yazar."""
    from src.db.database import get_db

    db = get_db()
    count = 0
    for snap in snapshots:
        db.insert_market_snapshot({
            "date": snap["date"],
            "ticker": snap["ticker"],
            "open": snap.get("open"),
            "high": snap.get("high"),
            "low": snap.get("low"),
            "close": snap.get("close"),
            "volume": snap.get("volume"),
            "change_pct": snap.get("change_pct"),
            "source": snap["source"],
            "extra_json": None,
        })
        count += 1
    logger.info("market_snapshots: %d kayıt yazıldı", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.db.database import get_db
    get_db().init()
    snapshots = fetch_all_tickers()
    saved = save_to_db(snapshots)
    print(f"Kaydedilen snapshot: {saved}")
    for s in snapshots[:5]:
        print(f"  {s['ticker']:15s} close={s['close']:>10.2f}  {s['change_pct']:+.2f}%  [{s['source']}]")
