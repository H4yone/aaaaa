"""
LAYER 1 — Kripto veri ingestion
CoinGecko free API (10-30 req/dk limit) — BTC, ETH + dominance
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

_COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_COINGECKO_PRO_BASE = "https://pro-api.coingecko.com/api/v3"


def _base_url() -> str:
    return _COINGECKO_PRO_BASE if os.getenv("COINGECKO_API_KEY") else _COINGECKO_BASE


def _headers() -> dict:
    key = os.getenv("COINGECKO_API_KEY", "")
    if key:
        return {"x-cg-pro-api-key": key}
    return {}


def _load_settings() -> dict:
    from pathlib import Path
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_prices(coin_ids: list[str], vs_currency: str = "usd") -> list[dict]:
    """
    Birden fazla coin için anlık fiyat + 24s değişim.
    CoinGecko /simple/price endpoint (ücretsiz, no key gerekmiyor).
    """
    if not coin_ids:
        return []

    ids_str = ",".join(coin_ids)
    params = {
        "ids": ids_str,
        "vs_currencies": vs_currency,
        "include_24hr_change": "true",
        "include_24hr_vol": "true",
        "include_market_cap": "true",
    }
    try:
        resp = requests.get(
            f"{_base_url()}/simple/price",
            params=params,
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except requests.RequestException as e:
        logger.error("CoinGecko /simple/price hata: %s", e)
        return []

    results: list[dict] = []
    today = str(date.today())
    for coin_id, values in raw.items():
        close = values.get(vs_currency)
        change = values.get(f"{vs_currency}_24h_change")
        volume = values.get(f"{vs_currency}_24h_vol")
        market_cap = values.get(f"{vs_currency}_market_cap")
        if close is None:
            continue
        results.append({
            "ticker": coin_id,
            "date": today,
            "open": None,
            "high": None,
            "low": None,
            "close": float(close),
            "volume": float(volume) if volume else None,
            "change_pct": round(float(change), 4) if change else None,
            "source": "coingecko",
            "extra_json": json.dumps({"market_cap": market_cap}),
        })
        logger.debug("CoinGecko %s: $%.2f  %+.2f%%", coin_id, close, change or 0)

    return results


def fetch_global_dominance() -> Optional[dict]:
    """Bitcoin dominance + toplam kripto market cap."""
    try:
        resp = requests.get(
            f"{_base_url()}/global",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        btc_dominance = data.get("market_cap_percentage", {}).get("btc")
        total_mcap = data.get("total_market_cap", {}).get("usd")
        return {
            "ticker": "crypto_global",
            "date": str(date.today()),
            "open": None,
            "high": None,
            "low": None,
            "close": round(float(btc_dominance), 4) if btc_dominance else None,
            "volume": None,
            "change_pct": None,
            "source": "coingecko",
            "extra_json": json.dumps({
                "btc_dominance_pct": btc_dominance,
                "total_market_cap_usd": total_mcap,
            }),
        }
    except (requests.RequestException, KeyError, TypeError) as e:
        logger.warning("CoinGecko global hata: %s", e)
        return None


def fetch_all_crypto() -> list[dict]:
    settings = _load_settings()
    crypto_cfg = settings.get("crypto", {})
    coin_ids: list[str] = crypto_cfg.get("coins", ["bitcoin", "ethereum"])
    vs_currency: str = crypto_cfg.get("vs_currency", "usd")

    results = fetch_prices(coin_ids, vs_currency)
    time.sleep(0.5)   # rate limit nezaketi
    dominance = fetch_global_dominance()
    if dominance:
        results.append(dominance)

    logger.info("CoinGecko: %d kayıt", len(results))
    return results


def save_to_db(crypto_data: list[dict]) -> int:
    from src.db.database import get_db
    db = get_db()
    for item in crypto_data:
        db.insert_market_snapshot(item)
    logger.info("crypto_snapshots: %d kayıt yazıldı", len(crypto_data))
    return len(crypto_data)


if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.db.database import get_db
    get_db().init()
    data = fetch_all_crypto()
    save_to_db(data)
    for d in data:
        print(f"  {d['ticker']:20s} close={d['close']}  {d.get('change_pct', 'N/A')}%")
