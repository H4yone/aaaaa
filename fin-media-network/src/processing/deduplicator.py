"""
LAYER 2 — Deduplication
3 aşamalı pipeline:
  1. URL hash — DB seviyesinde (INSERT OR IGNORE, zaten yapılıyor)
  2. rapidfuzz title fuzzy match — aynı gün içinde eşik ≥ 90 = duplicate
  3. TF-IDF cosine similarity — cross-source, cosine ≥ 0.85 = duplicate
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


def _load_settings() -> dict:
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── TF-IDF cosine (embedding-free, dependency-free) ───────────────────────────

_STOPWORDS = {
    "bir", "bu", "ve", "ile", "de", "da", "için", "olan", "oldu", "the", "a",
    "an", "of", "in", "on", "at", "to", "is", "are", "was", "were", "has",
    "have", "had", "be", "been", "being", "that", "this", "it", "its",
}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zçğıöşüa-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = defaultdict(float)
    for t in tokens:
        tf[t] += 1.0
    n = len(tokens) or 1
    return {t: (cnt / n) * idf.get(t, 1.0) for t, cnt in tf.items()}


def _cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    mag1 = math.sqrt(sum(x * x for x in v1.values()))
    mag2 = math.sqrt(sum(x * x for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def _build_idf(corpus: list[list[str]]) -> dict[str, float]:
    N = len(corpus) or 1
    df: dict[str, int] = defaultdict(int)
    for tokens in corpus:
        for t in set(tokens):
            df[t] += 1
    return {t: math.log(N / cnt) for t, cnt in df.items()}


# ── Ana dedup fonksiyonları ───────────────────────────────────────────────────

def mark_fuzzy_duplicates(
    rows: list[dict],
    threshold: int = 90,
) -> list[dict]:
    """
    rapidfuzz ile başlık benzerliği ≥ threshold olan haberleri duplicate işaret eder.
    Rows içindeki her dict'e 'is_duplicate' key'i eklenir.
    İlk görülen haber orijinal, sonrakiler duplicate.
    """
    titles: list[str] = []
    result: list[dict] = []

    for row in rows:
        title = row.get("title", "")
        if not titles:
            row["is_duplicate"] = 0
            titles.append(title)
            result.append(row)
            continue

        best = process.extractOne(
            title, titles, scorer=fuzz.token_sort_ratio
        )
        if best and best[1] >= threshold:
            row["is_duplicate"] = 1
            logger.debug("Fuzzy dup [%d%%]: '%s'", best[1], title[:60])
        else:
            row["is_duplicate"] = 0
            titles.append(title)
        result.append(row)

    dup_count = sum(1 for r in result if r["is_duplicate"])
    logger.info("Fuzzy dedup: %d/%d duplicate işaretlendi", dup_count, len(rows))
    return result


def mark_cosine_duplicates(
    rows: list[dict],
    threshold: float = 0.85,
) -> list[dict]:
    """
    TF-IDF cosine ≥ threshold olan non-duplicate çiftleri duplicate işaret eder.
    Fuzzy dedup sonrası çalıştırılmalı.
    """
    non_dup = [r for r in rows if not r.get("is_duplicate")]
    if len(non_dup) < 2:
        return rows

    corpus = [_tokenize(r.get("title", "") + " " + (r.get("summary") or ""))
              for r in non_dup]
    idf = _build_idf(corpus)
    vectors = [_tfidf_vector(tokens, idf) for tokens in corpus]

    duplicate_indices: set[int] = set()
    for i in range(len(non_dup)):
        if i in duplicate_indices:
            continue
        for j in range(i + 1, len(non_dup)):
            if j in duplicate_indices:
                continue
            sim = _cosine(vectors[i], vectors[j])
            if sim >= threshold:
                duplicate_indices.add(j)
                logger.debug(
                    "Cosine dup [%.2f]: '%s'",
                    sim,
                    non_dup[j].get("title", "")[:60],
                )

    marked = 0
    nd_idx = 0
    result: list[dict] = []
    for row in rows:
        if row.get("is_duplicate"):
            result.append(row)
            continue
        if nd_idx in duplicate_indices:
            row["is_duplicate"] = 1
            marked += 1
        result.append(row)
        nd_idx += 1

    logger.info("Cosine dedup: %d ek duplicate işaretlendi", marked)
    return result


def run_deduplication(rows: list[dict]) -> list[dict]:
    """Tam 3-aşamalı dedup pipeline (Stage 1 = DB seviyesinde yapılmış)."""
    settings = _load_settings()
    dedup_cfg = settings.get("deduplication", {})
    fuzzy_thresh = int(dedup_cfg.get("fuzzy_threshold", 90))
    cosine_thresh = float(dedup_cfg.get("embedding_cosine", 0.85))

    rows = mark_fuzzy_duplicates(rows, threshold=fuzzy_thresh)
    rows = mark_cosine_duplicates(rows, threshold=cosine_thresh)
    return rows


def update_db_duplicates(rows: list[dict]) -> int:
    """Duplicate işaretli satırları DB'de günceller."""
    from src.db.database import get_db
    db = get_db()
    updated = 0
    with db.get_conn() as conn:
        for row in rows:
            if row.get("is_duplicate"):
                conn.execute(
                    "UPDATE raw_news SET is_duplicate=1 WHERE url_hash=?",
                    (row["url_hash"],),
                )
                updated += 1
    logger.info("DB güncellendi: %d duplicate işaretlendi", updated)
    return updated
