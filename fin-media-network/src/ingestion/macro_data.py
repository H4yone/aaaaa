"""
LAYER 1 — Makro veri ingestion
FRED API (fed faiz, CPI, 10Y) + TCMB EVDS (politika faizi, rezervler)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import requests
import yaml

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"


def _load_settings() -> dict:
    from pathlib import Path
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── FRED ─────────────────────────────────────────────────────────────────────

def _fetch_fred_series(series_id: str, api_key: str, limit: int = 5) -> Optional[dict]:
    """Belirtilen FRED serisi için en son N gözlemi çeker."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
        "observation_start": str(date.today() - timedelta(days=90)),
    }
    try:
        resp = requests.get(_FRED_BASE, params=params, timeout=10)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        # "." değerlerini filtrele (veri yok)
        valid = [o for o in obs if o.get("value") not in (".", "", None)]
        if not valid:
            return None
        latest = valid[0]
        return {
            "ticker": series_id,
            "date": latest["date"],
            "close": float(latest["value"]),
            "open": None,
            "high": None,
            "low": None,
            "volume": None,
            "change_pct": _calc_change(valid),
            "source": "fred",
            "extra_json": json.dumps({"series_id": series_id, "recent": valid[:3]}),
        }
    except requests.RequestException as e:
        logger.warning("FRED hata [%s]: %s", series_id, e)
        return None


def _calc_change(observations: list[dict]) -> Optional[float]:
    if len(observations) < 2:
        return None
    try:
        curr = float(observations[0]["value"])
        prev = float(observations[1]["value"])
        return round(curr - prev, 4)   # faiz için % fark, bps değil
    except (ValueError, KeyError):
        return None


def fetch_fred_all() -> list[dict]:
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.warning("FRED_API_KEY ayarlı değil — makro veri atlanıyor")
        return []

    settings = _load_settings()
    series_map: dict = settings.get("fred", {}).get("series", {})
    results: list[dict] = []
    for series_id in series_map:
        data = _fetch_fred_series(series_id, api_key)
        if data:
            results.append(data)
            logger.debug("FRED %s: %.4f", series_id, data["close"])
    logger.info("FRED: %d/%d seri çekildi", len(results), len(series_map))
    return results


# ── TCMB EVDS ────────────────────────────────────────────────────────────────

def _fetch_evds_series(series_id: str, api_key: str) -> Optional[dict]:
    """TCMB EVDS REST API — tek seri, son 30 günlük veri."""
    start = str(date.today() - timedelta(days=30))
    start_fmt = datetime.strptime(start, "%Y-%m-%d").strftime("%d-%m-%Y")
    end_fmt = datetime.today().strftime("%d-%m-%Y")

    params = {
        "series": series_id,
        "startDate": start_fmt,
        "endDate": end_fmt,
        "type": "json",
        "key": api_key,
    }
    try:
        resp = requests.get(f"{_EVDS_BASE}/series", params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items", [])
        if not items:
            return None
        # EVDS items'ı tarihe göre sıralar
        valid = [i for i in items if i.get(series_id) not in (None, "")]
        if not valid:
            return None
        latest = valid[-1]
        value = float(str(latest[series_id]).replace(",", "."))
        date_str = latest.get("Tarih", "")
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m")
                date_str = str(date_obj.date())
            except ValueError:
                pass
        return {
            "ticker": series_id,
            "date": date_str or str(date.today()),
            "close": value,
            "open": None,
            "high": None,
            "low": None,
            "volume": None,
            "change_pct": None,
            "source": "evds",
            "extra_json": json.dumps({"series_id": series_id}),
        }
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("EVDS hata [%s]: %s", series_id, e)
        return None


def fetch_evds_all() -> list[dict]:
    api_key = os.getenv("EVDS_API_KEY", "")
    if not api_key:
        logger.warning("EVDS_API_KEY ayarlı değil — TCMB veri atlanıyor")
        return []

    settings = _load_settings()
    series_list: list[dict] = settings.get("evds", {}).get("series", [])
    results: list[dict] = []
    for item in series_list:
        series_id = item["series_id"]
        data = _fetch_evds_series(series_id, api_key)
        if data:
            results.append(data)
            logger.debug("EVDS %s: %.4f", series_id, data["close"])
    logger.info("EVDS: %d/%d seri çekildi", len(results), len(series_list))
    return results


# ── Birleşik çekme ────────────────────────────────────────────────────────────

def fetch_all_macro() -> list[dict]:
    """FRED + EVDS verilerini birleştirir."""
    return fetch_fred_all() + fetch_evds_all()


def save_to_db(macro_data: list[dict]) -> int:
    from src.db.database import get_db
    db = get_db()
    for item in macro_data:
        db.insert_market_snapshot(item)
    logger.info("macro_snapshots: %d kayıt yazıldı", len(macro_data))
    return len(macro_data)


if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.db.database import get_db
    get_db().init()
    data = fetch_all_macro()
    save_to_db(data)
    for d in data:
        print(f"  {d['ticker']:20s} = {d['close']}  [{d['source']}]")
