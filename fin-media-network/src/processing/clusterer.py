"""
LAYER 2 — Event Clustering
Aynı olayı anlatan haberleri tek cluster altında toplar.
Strateji:
  1. Tier-1/2 scored haberleri al
  2. rapidfuzz token_sort_ratio ≥ 70 + ortak ticker → aynı cluster
  3. Her cluster için en yüksek kaynaklı haber representative seçilir
  4. clusters tablosuna yaz, raw_news.cluster_id güncelle
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import yaml
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_CLUSTER_FUZZY_THRESHOLD = 70
_CLUSTER_TICKER_BONUS = True   # ortak ticker varsa eşik düşer


def _load_settings() -> dict:
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _tickers(row: dict) -> set[str]:
    try:
        rj = json.loads(row.get("raw_json") or "{}")
        return set(rj.get("tickers_mentioned", []))
    except (json.JSONDecodeError, TypeError):
        return set()


def _effective_threshold(row_a: dict, row_b: dict) -> int:
    """Ortak ticker varsa daha düşük başlık benzerliği yeterli."""
    if _CLUSTER_TICKER_BONUS and (_tickers(row_a) & _tickers(row_b)):
        return _CLUSTER_FUZZY_THRESHOLD - 15   # 55'e düş
    return _CLUSTER_FUZZY_THRESHOLD


def cluster_rows(rows: list[dict]) -> list[list[dict]]:
    """
    Haberleri gruplara ayırır.
    Returns: cluster listesi — her cluster bir list[dict].
    """
    if not rows:
        return []

    clusters: list[list[dict]] = []
    assigned = [False] * len(rows)

    for i, row in enumerate(rows):
        if assigned[i]:
            continue
        cluster = [row]
        assigned[i] = True
        for j in range(i + 1, len(rows)):
            if assigned[j]:
                continue
            threshold = _effective_threshold(row, rows[j])
            sim = fuzz.token_sort_ratio(
                row.get("title", ""), rows[j].get("title", "")
            )
            if sim >= threshold:
                cluster.append(rows[j])
                assigned[j] = True
        clusters.append(cluster)

    logger.info("Clusterer: %d haber → %d cluster", len(rows), len(clusters))
    return clusters


def _representative(cluster: list[dict]) -> dict:
    """En yüksek source_weight'li haberi representative seç."""
    def sw(row: dict) -> float:
        try:
            return float(json.loads(row.get("raw_json") or "{}").get("source_weight", 0))
        except Exception:
            return 0.0

    return max(cluster, key=sw)


def build_cluster_records(
    clusters: list[list[dict]],
    run_date: str,
) -> list[dict]:
    """
    clusters tablosuna yazılacak dict listesi üretir.
    Her cluster için aggregate skor hesaplanır.
    """
    records: list[dict] = []
    for cluster in clusters:
        rep = _representative(cluster)

        # Aggregate değerler
        source_weight = max(
            (float(json.loads(r.get("raw_json") or "{}").get("source_weight", 0))
             for r in cluster),
            default=0.0,
        )
        market_relevance = max(
            (float(r.get("market_relevance", 0)) for r in cluster), default=0.0
        )
        volatility_impact = max(
            (float(r.get("volatility_impact", 0)) for r in cluster), default=0.0
        )
        score = max((float(r.get("score", 0)) for r in cluster), default=0.0)
        tier_vals = [r.get("tier") for r in cluster if r.get("tier") is not None]
        tier = min(tier_vals) if tier_vals else None   # en iyi tier (1 < 2)

        # Tüm ticker'ları birleştir
        all_tickers: set[str] = set()
        for r in cluster:
            all_tickers |= (
                set(json.loads(r.get("raw_json") or "{}").get("tickers_mentioned", []))
            )

        # Keyword birleştir
        words = set()
        for r in cluster:
            words.update((r.get("title") or "").lower().split())
        keywords = list(words)[:20]   # ilk 20 kelime

        records.append({
            "date": run_date,
            "representative_title": rep.get("title", ""),
            "news_count": len(cluster),
            "source_weight": round(source_weight, 4),
            "market_relevance": round(market_relevance, 4),
            "volatility_impact": round(volatility_impact, 4),
            "score": round(score, 2),
            "tier": tier,
            "keywords": json.dumps(keywords),
            "tickers_mentioned": json.dumps(sorted(all_tickers)),
            "_member_hashes": [r.get("url_hash") for r in cluster],
        })

    return records


def save_clusters_to_db(records: list[dict]) -> list[int]:
    """Cluster kayıtlarını DB'ye yazar, oluşan ID'leri döner."""
    from src.db.database import get_db
    db = get_db()
    cluster_ids: list[int] = []

    for rec in records:
        member_hashes = rec.pop("_member_hashes", [])
        cluster_id = db.insert_cluster(rec)
        cluster_ids.append(cluster_id)

        # raw_news satırlarını cluster_id ile güncelle
        with db.get_conn() as conn:
            for h in member_hashes:
                conn.execute(
                    "UPDATE raw_news SET cluster_id=? WHERE url_hash=?",
                    (cluster_id, h),
                )

    logger.info("DB: %d cluster kaydedildi", len(cluster_ids))
    return cluster_ids


def run_clustering(
    scored_rows: list[dict],
    run_date: Optional[str] = None,
) -> list[dict]:
    """
    Tam clustering pipeline:
    1. Tier-1/2 haberleri cluster'lar
    2. DB'ye yazar
    3. Cluster record listesini döner
    """
    from typing import Optional
    if run_date is None:
        run_date = str(date.today())

    # Sadece Tier-1 ve Tier-2 haberleri cluster'la
    relevant = [r for r in scored_rows if r.get("tier") in (1, 2)]
    if not relevant:
        logger.warning("Cluster için Tier-1/2 haber yok")
        return []

    clusters = cluster_rows(relevant)
    records = build_cluster_records(clusters, run_date)
    return records


# Optional type import düzeltmesi
from typing import Optional   # noqa: E402  (module-level için)
