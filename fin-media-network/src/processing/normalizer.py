"""
LAYER 2 — Normalizasyon
raw_news'teki haberleri temizler:
  - Timestamp → UTC standart format
  - Ticker mapping (raw_json içindeki ticker alanı)
  - Source weight lookup (source_weights.yaml'dan)
  - TR saati gösterimi için yardımcı fonksiyon
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_TR_TZ = timezone(timedelta(hours=3))   # UTC+3 (Türkiye)


def _load_source_weights() -> dict:
    with open(Path("config/source_weights.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_source_weight_index(cfg: dict) -> dict[str, float]:
    """Domain → ağırlık sözlüğü."""
    index: dict[str, float] = {}
    for tier_key, tier_val in cfg.items():
        if not isinstance(tier_val, dict):
            continue
        weight = float(tier_val.get("weight", 0.5))
        for domain in tier_val.get("sources", []):
            index[domain.lower()] = weight
    return index


_SOURCE_WEIGHT_INDEX: dict[str, float] = {}


def _get_weight_index() -> dict[str, float]:
    global _SOURCE_WEIGHT_INDEX
    if not _SOURCE_WEIGHT_INDEX:
        cfg = _load_source_weights()
        _SOURCE_WEIGHT_INDEX = _build_source_weight_index(cfg)
    return _SOURCE_WEIGHT_INDEX


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def to_utc_str(raw: Optional[str]) -> Optional[str]:
    """Herhangi bir datetime string'ini UTC'ye çevirir."""
    if not raw:
        return None
    # Zaten normalize ise direkt dön
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", raw):
        return raw
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw[:30], fmt)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    logger.debug("Timestamp parse edilemedi: %s", raw)
    return None


def utc_to_tr(utc_str: str) -> str:
    """UTC datetime string'ini TR (UTC+3) saatine çevirir."""
    dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(_TR_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ── Source weight lookup ──────────────────────────────────────────────────────

def get_source_weight(source_url: Optional[str], source_name: Optional[str] = None) -> float:
    """URL veya isimden kaynak ağırlığı döner."""
    idx = _get_weight_index()
    candidates = []
    if source_url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(source_url).netloc.lower().replace("www.", "")
            candidates.append(domain)
        except Exception:
            pass
    if source_name:
        candidates.append(source_name.lower().replace("www.", ""))

    for candidate in candidates:
        if candidate in idx:
            return idx[candidate]
        # Partial match: "finance.yahoo.com" → "yahoo.com"
        for domain, weight in idx.items():
            if domain in candidate:
                return weight

    # Google News bilinmeyen kaynak
    if source_url and "news.google.com" in source_url:
        return 0.4

    cfg = _load_source_weights()
    return float(cfg.get("tier_unknown", {}).get("weight", 0.4))


# ── Ticker extraction ─────────────────────────────────────────────────────────

_BIST_TICKER_RE = re.compile(r"\b([A-Z]{3,6})\.IS\b")
_GLOBAL_TICKER_RE = re.compile(r"\b(NVDA|AAPL|MSFT|META|GOOGL|AMZN|TSLA|SPX|NDX)\b")

_KEYWORD_TICKER_MAP = {
    "garanti": "GARAN.IS",
    "akbank": "AKBNK.IS",
    "yapı kredi": "YKBNK.IS",
    "yapi kredi": "YKBNK.IS",
    "türk hava": "THYAO.IS",
    "thy ": "THYAO.IS",
    "pegasus": "PGSUS.IS",
    "tüpraş": "TUPRS.IS",
    "tupras": "TUPRS.IS",
    "aselsan": "ASELS.IS",
    "koç holding": "KCHOL.IS",
    "koc holding": "KCHOL.IS",
    "sabancı": "SAHOL.IS",
    "sabanci": "SAHOL.IS",
    "şişecam": "SISE.IS",
    "sisecam": "SISE.IS",
    "bist 100": "XU100.IS",
    "xu100": "XU100.IS",
    "borsa istanbul": "XU100.IS",
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "s&p 500": "^GSPC",
    "nasdaq": "^NDX",
    "fed ": "FEDFUNDS",
    "federal reserve": "FEDFUNDS",
    "tcmb": "TP.TG2.Y01",
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth ": "ethereum",
}


def extract_tickers(text: str) -> list[str]:
    """Başlık veya metin içindeki ticker'ları çıkarır."""
    found: set[str] = set()
    text_lower = text.lower()

    for keyword, ticker in _KEYWORD_TICKER_MAP.items():
        if keyword in text_lower:
            found.add(ticker)

    for m in _BIST_TICKER_RE.finditer(text.upper()):
        found.add(m.group(0))

    for m in _GLOBAL_TICKER_RE.finditer(text.upper()):
        found.add(m.group(1))

    return sorted(found)


# ── Ana normalize fonksiyonu ──────────────────────────────────────────────────

def normalize_row(row: dict) -> dict:
    """
    raw_news satırını normalize eder:
    - published_at → UTC
    - source_weight hesaplar
    - tickers_mentioned çıkarır
    Orijinal satırı değiştirmez, yeni dict döner.
    """
    normalized = dict(row)
    normalized["published_at"] = to_utc_str(row.get("published_at"))

    sw = get_source_weight(row.get("source_url"), row.get("source_name"))

    text = (row.get("title") or "") + " " + (row.get("summary") or "")
    tickers = extract_tickers(text)

    # raw_json'u zenginleştir
    try:
        rj = json.loads(row.get("raw_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        rj = {}
    rj["source_weight"] = sw
    rj["tickers_mentioned"] = tickers
    normalized["raw_json"] = json.dumps(rj)

    return normalized


def normalize_batch(rows: list[dict]) -> list[dict]:
    return [normalize_row(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = {
        "url_hash": "abc",
        "url": "https://finance.yahoo.com/news/test",
        "title": "Garanti Bankası BIST 100'de öne çıktı — Fed kararı bekleniyor",
        "summary": "GARAN.IS hisseleri yükseldi",
        "source_name": "finance.yahoo.com",
        "source_url": "https://finance.yahoo.com/rss/topstories",
        "published_at": "Thu, 11 Jun 2026 06:00:00 GMT",
        "feed_name": "yahoo_topstories",
        "raw_json": None,
    }
    result = normalize_row(sample)
    print("Normalize sonucu:")
    print(f"  published_at: {result['published_at']}")
    rj = json.loads(result["raw_json"])
    print(f"  source_weight: {rj['source_weight']}")
    print(f"  tickers: {rj['tickers_mentioned']}")
