"""
LAYER 2 — Credibility & Impact Scoring (kural tabanlı, LLM'siz = $0)

score = 0.35 × source_weight
      + 0.35 × market_relevance   (0–1, ticker/keyword yoğunluğu)
      + 0.30 × volatility_impact  (0–1, kategori bazlı)

≥ 70 → Tier-1 | 40–70 → Tier-2 | <40 → arşiv
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _load_source_weights_cfg() -> dict:
    with open(Path("config/source_weights.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_settings() -> dict:
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Volatility kategori tespiti ───────────────────────────────────────────────

_VOLATILITY_RULES: list[tuple[float, list[str]]] = [
    (1.0, ["faiz kararı", "interest rate decision", "fomc", "merkez bankası kararı",
           "tcmb kararı", "rate decision", "politika faizi"]),
    (0.9, ["earnings", "net kâr", "net kar", "finansal tablolar", "kar açıkladı",
           "quarterly results", "kap bildirimi", "özel durum", "temettü"]),
    (0.8, ["savaş", "war", "jeopolitik", "geopolitical", "yaptırım", "sanctions",
           "nato", "kriz", "crisis", "çatışma", "conflict"]),
    (0.8, ["cpi", "enflasyon", "inflation", "gdp", "büyüme", "işsizlik",
           "unemployment", "pce", "pmi", "nfp", "jobs report", "gdp report"]),
    (0.7, ["ipo", "halka arz", "birleşme", "satın alma", "merger", "acquisition",
           "devralma", "ortak girişim"]),
    (0.6, ["opec", "petrol üretim", "oil output", "oil production"]),
    (0.5, ["analist", "analyst", "hedef fiyat revizyon", "rating change",
           "upgrade", "downgrade", "buy rating", "sell rating"]),
    (0.4, ["opsiyon vade", "option expiry", "vix"]),
    (0.2, []),  # genel haber — default
]

_MARKET_KEYWORDS = [
    "bist", "borsa", "hisse", "endeks", "faiz", "kur", "dolar", "euro",
    "petrol", "altın", "kripto", "bitcoin", "ethereum", "fed", "tcmb",
    "enflasyon", "büyüme", "recession", "market", "stock", "index",
    "yield", "bond", "treasury", "nasdaq", "s&p", "dow", "rally",
    "sell-off", "volatility", "earnings", "gdp", "cpi",
]


def _detect_volatility_impact(text: str) -> float:
    text_lower = text.lower()
    for impact, keywords in _VOLATILITY_RULES[:-1]:
        for kw in keywords:
            if kw in text_lower:
                return impact
    return 0.2


def _calc_market_relevance(text: str, tickers: list[str]) -> float:
    """
    0–1 arası market relevance skoru.
    Ticker varlığı + keyword yoğunluğu bileşimi.
    """
    text_lower = text.lower()
    words = text_lower.split()
    total = len(words) or 1

    # Ticker puanı (her benzersiz ticker +0.15, max 0.45)
    ticker_score = min(len(set(tickers)) * 0.15, 0.45)

    # Keyword yoğunluğu (eşleşen keyword / toplam kelime, normalize)
    kw_matches = sum(1 for kw in _MARKET_KEYWORDS if kw in text_lower)
    kw_density = min(kw_matches / max(total / 20, 1), 1.0)   # ~20 kelimede 1 match = 1.0

    return round(min(ticker_score + kw_density * 0.55, 1.0), 4)


def score_row(row: dict) -> dict:
    """
    Tek raw_news satırını skorlar.
    Returns dict with: source_weight, market_relevance, volatility_impact, score, tier
    """
    # source_weight — raw_json'dan veya varsayılan
    try:
        rj = json.loads(row.get("raw_json") or "{}")
        source_weight = float(rj.get("source_weight", 0.4))
        tickers = rj.get("tickers_mentioned", [])
    except (json.JSONDecodeError, TypeError):
        source_weight = 0.4
        tickers = []

    text = (row.get("title") or "") + " " + (row.get("summary") or "")

    market_relevance = _calc_market_relevance(text, tickers)
    volatility_impact = _detect_volatility_impact(text)

    raw_score = (
        0.35 * source_weight
        + 0.35 * market_relevance
        + 0.30 * volatility_impact
    ) * 100   # 0–100 ölçeğine çevir

    score = round(raw_score, 2)

    settings = _load_settings()
    scoring = settings.get("scoring", {})
    tier1_thresh = scoring.get("tier1_threshold", 70)
    tier2_min = scoring.get("tier2_min", 40)

    if score >= tier1_thresh:
        tier = 1
    elif score >= tier2_min:
        tier = 2
    else:
        tier = None   # arşiv

    return {
        "source_weight": source_weight,
        "market_relevance": market_relevance,
        "volatility_impact": volatility_impact,
        "score": score,
        "tier": tier,
    }


def score_batch(rows: list[dict]) -> list[dict]:
    """Her satıra skor alanlarını ekleyerek döner."""
    results = []
    for row in rows:
        scored = dict(row)
        scored.update(score_row(row))
        results.append(scored)

    tier1 = sum(1 for r in results if r.get("tier") == 1)
    tier2 = sum(1 for r in results if r.get("tier") == 2)
    logger.info("Scoring: %d Tier-1, %d Tier-2, %d arşiv",
                tier1, tier2, len(results) - tier1 - tier2)
    return results


def get_tier_breakdown(rows: list[dict]) -> dict:
    t1 = [r for r in rows if r.get("tier") == 1]
    t2 = [r for r in rows if r.get("tier") == 2]
    arch = [r for r in rows if r.get("tier") is None]
    return {"tier1": t1, "tier2": t2, "archive": arch}
