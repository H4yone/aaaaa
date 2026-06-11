"""
Gün 4 testi: deduplicator, scorer, clusterer
test_scorer.py — build planındaki "✅ Çıktı" dosyası
"""
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

_CONFIG = Path(__file__).parent.parent / "config"


@pytest.fixture
def project_env(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    for fname in ("settings.yaml", "source_weights.yaml"):
        shutil.copy(_CONFIG / fname, tmp_path / "config" / fname)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ─── Scorer tests ─────────────────────────────────────────────────────────────

from src.processing.scorer import (
    score_row,
    score_batch,
    get_tier_breakdown,
    _detect_volatility_impact,
    _calc_market_relevance,
)


def test_score_row_fed_decision_is_tier1(project_env):
    row = {
        "title": "Fed interest rate decision: FOMC keeps rates unchanged",
        "summary": "Federal Reserve policy meeting outcome affects global markets",
        "raw_json": json.dumps({"source_weight": 1.0, "tickers_mentioned": ["FEDFUNDS", "^TNX"]}),
    }
    result = score_row(row)
    assert result["tier"] == 1
    assert result["score"] >= 70
    assert result["volatility_impact"] == 1.0


def test_score_row_earnings_beat_is_tier1(project_env):
    row = {
        "title": "Garanti Bankası güçlü kâr açıkladı — earnings beklentilerin üzerinde",
        "summary": "Net kar rekor seviyede",
        "raw_json": json.dumps({"source_weight": 1.0, "tickers_mentioned": ["GARAN.IS"]}),
    }
    result = score_row(row)
    assert result["tier"] in (1, 2)
    assert result["volatility_impact"] == 0.9


def test_score_row_geopolitical_is_high(project_env):
    row = {
        "title": "Bölgede jeopolitik gerilim arttı, savaş riski yükseliyor",
        "summary": "Conflict in the region raises risk premium",
        "raw_json": json.dumps({"source_weight": 0.8, "tickers_mentioned": ["XU100.IS"]}),
    }
    result = score_row(row)
    assert result["volatility_impact"] == 0.8
    assert result["score"] > 40


def test_score_row_general_news_is_archive(project_env):
    row = {
        "title": "Hava güzel bugün, insanlar dışarı çıktı",
        "summary": "Genel haber, finans ile ilgisi yok",
        "raw_json": json.dumps({"source_weight": 0.4, "tickers_mentioned": []}),
    }
    result = score_row(row)
    assert result["tier"] is None
    assert result["score"] < 40


def test_score_batch_returns_all(project_env):
    rows = [
        {
            "title": "FOMC faiz kararı açıklandı",
            "summary": "",
            "raw_json": json.dumps({"source_weight": 1.0, "tickers_mentioned": ["FEDFUNDS"]}),
        },
        {
            "title": "Borsa İstanbul BIST 100 endeksi yükseldi",
            "summary": "",
            "raw_json": json.dumps({"source_weight": 0.8, "tickers_mentioned": ["XU100.IS"]}),
        },
        {
            "title": "Haber başlığı alakasız içerik",
            "summary": "",
            "raw_json": json.dumps({"source_weight": 0.4, "tickers_mentioned": []}),
        },
    ]
    scored = score_batch(rows)
    assert len(scored) == 3
    assert all("score" in r for r in scored)
    assert all("tier" in r for r in scored)


def test_tier_breakdown(project_env):
    rows = [
        {"title": "FOMC faiz kararı", "summary": "", "raw_json": json.dumps({"source_weight": 1.0, "tickers_mentioned": ["FEDFUNDS"]})},
        {"title": "Borsa güncelleme", "summary": "", "raw_json": json.dumps({"source_weight": 0.8, "tickers_mentioned": ["XU100.IS"]})},
        {"title": "Genel haber yok", "summary": "", "raw_json": json.dumps({"source_weight": 0.4, "tickers_mentioned": []})},
    ]
    scored = score_batch(rows)
    breakdown = get_tier_breakdown(scored)
    assert "tier1" in breakdown
    assert "tier2" in breakdown
    assert "archive" in breakdown
    total = len(breakdown["tier1"]) + len(breakdown["tier2"]) + len(breakdown["archive"])
    assert total == 3


def test_volatility_impact_hierarchy(project_env):
    assert _detect_volatility_impact("faiz kararı açıklandı") == 1.0
    assert _detect_volatility_impact("earnings net kâr açıklandı") == 0.9
    assert _detect_volatility_impact("jeopolitik kriz çatışma") == 0.8
    assert _detect_volatility_impact("cpi enflasyon verisi") == 0.8
    assert _detect_volatility_impact("analist rating change") == 0.5
    assert _detect_volatility_impact("hava güzel bugün") == 0.2


def test_market_relevance_with_tickers():
    score = _calc_market_relevance("BIST 100 endeksi yükseldi", ["XU100.IS", "GARAN.IS"])
    assert score > 0.3


def test_market_relevance_no_match():
    score = _calc_market_relevance("Bugün hava çok güzel ve insanlar parkta", [])
    assert score < 0.3


# ─── Deduplicator tests ───────────────────────────────────────────────────────

from src.processing.deduplicator import (
    mark_fuzzy_duplicates,
    mark_cosine_duplicates,
    run_deduplication,
)


def _make_row(url_hash: str, title: str, summary: str = "") -> dict:
    return {
        "url_hash": url_hash,
        "url": f"https://example.com/{url_hash}",
        "title": title,
        "summary": summary,
        "source_name": "test",
        "raw_json": json.dumps({"source_weight": 0.8, "tickers_mentioned": []}),
    }


def test_fuzzy_dedup_marks_near_duplicate():
    rows = [
        _make_row("a1", "Fed keeps interest rates unchanged at FOMC meeting"),
        _make_row("a2", "Fed keeps interest rate unchanged at FOMC"),   # ~92% benzer
        _make_row("a3", "Borsa İstanbul bugün güçlü açılış yaptı"),    # farklı konu
    ]
    result = mark_fuzzy_duplicates(rows, threshold=85)
    dup_flags = [r["is_duplicate"] for r in result]
    assert dup_flags[0] == 0   # orijinal
    assert dup_flags[1] == 1   # duplicate
    assert dup_flags[2] == 0   # farklı konu


def test_fuzzy_dedup_all_unique():
    rows = [
        _make_row("b1", "Fed faiz kararı açıklandı"),
        _make_row("b2", "BIST 100 endeksi yükseldi"),
        _make_row("b3", "Bitcoin rekor kırdı"),
    ]
    result = mark_fuzzy_duplicates(rows, threshold=90)
    assert all(r["is_duplicate"] == 0 for r in result)


def test_cosine_dedup_catches_paraphrase():
    # TF-IDF gerçek kelime örtüşümüne dayanır — aynı kelimeler farklı sırayla
    rows = [
        _make_row("c1", "Fed raises benchmark interest rates inflation concerns",
                  "Federal Reserve hikes rates amid rising inflation"),
        _make_row("c2", "raises benchmark interest rates inflation concerns Fed",
                  "hikes rates amid rising inflation Federal Reserve"),
    ]
    rows = mark_fuzzy_duplicates(rows, threshold=95)   # çok benzer başlıklar geçer
    result = mark_cosine_duplicates(rows, threshold=0.85)
    dup_count = sum(1 for r in result if r["is_duplicate"])
    assert dup_count >= 1


def test_run_deduplication_full_pipeline(project_env):
    rows = [
        _make_row("d1", "FOMC Fed faiz kararı açıklandı piyasalar etkilendi"),
        _make_row("d2", "Fed FOMC faiz kararı açıklandı — piyasalar etkilendi"),   # near dup
        _make_row("d3", "Garanti Bankası net kâr açıkladı bist endeksi"),
        _make_row("d4", "Bitcoin BTC rekor seviyeye ulaştı kripto"),
    ]
    result = run_deduplication(rows)
    dup_count = sum(1 for r in result if r.get("is_duplicate"))
    assert dup_count >= 1
    assert len(result) == 4   # tüm satırlar dönmeli (silinmez, işaretlenir)


# ─── Clusterer tests ──────────────────────────────────────────────────────────

from src.processing.clusterer import (
    cluster_rows,
    build_cluster_records,
    run_clustering,
)


def _scored_row(url_hash: str, title: str, tier: int, score: float,
                tickers: list | None = None) -> dict:
    return {
        "url_hash": url_hash,
        "title": title,
        "summary": "",
        "tier": tier,
        "score": score,
        "market_relevance": 0.5,
        "volatility_impact": 0.8,
        "raw_json": json.dumps({
            "source_weight": 0.9,
            "tickers_mentioned": tickers or [],
        }),
    }


def test_cluster_rows_groups_similar():
    rows = [
        _scored_row("e1", "Fed faiz kararı piyasaları sarstı", 1, 85.0, ["FEDFUNDS"]),
        _scored_row("e2", "Fed faiz kararı piyasaları sarstı bugün", 1, 80.0, ["FEDFUNDS"]),
        _scored_row("e3", "Borsa İstanbul BIST 100 yükseldi", 2, 55.0, ["XU100.IS"]),
    ]
    clusters = cluster_rows(rows)
    # Fed haberleri aynı cluster'da olmalı
    assert len(clusters) == 2
    assert any(len(c) == 2 for c in clusters)


def test_cluster_rows_all_unique():
    rows = [
        _scored_row("f1", "Fed faiz artırdı", 1, 85.0),
        _scored_row("f2", "Borsa yükseldi", 2, 55.0),
        _scored_row("f3", "Bitcoin rekor kırdı", 2, 50.0),
    ]
    clusters = cluster_rows(rows)
    assert len(clusters) == 3


def test_build_cluster_records(project_env):
    rows = [
        _scored_row("g1", "Fed hawkish tutum piyasalara yansıdı", 1, 85.0, ["FEDFUNDS", "^TNX"]),
        _scored_row("g2", "Fed hawkish yansıması piyasalarda hissedildi", 1, 80.0, ["FEDFUNDS"]),
    ]
    clusters = cluster_rows(rows)
    records = build_cluster_records(clusters, "2026-06-11")
    assert len(records) >= 1
    rec = records[0]
    assert rec["date"] == "2026-06-11"
    assert rec["news_count"] >= 1
    assert rec["score"] > 0
    assert "FEDFUNDS" in json.loads(rec["tickers_mentioned"])


def test_run_clustering_filters_archive(project_env):
    rows = [
        _scored_row("h1", "Fed faiz kararı", 1, 85.0),
        _scored_row("h2", "Borsa BIST yükseliş", 2, 55.0),
        {   # arşiv satırı — tier=None
            "url_hash": "h3",
            "title": "Genel haber",
            "summary": "",
            "tier": None,
            "score": 15.0,
            "market_relevance": 0.1,
            "volatility_impact": 0.2,
            "raw_json": json.dumps({"source_weight": 0.4, "tickers_mentioned": []}),
        },
    ]
    records = run_clustering(rows, "2026-06-11")
    # Arşiv haberi cluster'a girmemeli
    total_news = sum(r["news_count"] for r in records)
    assert total_news == 2


def test_run_clustering_empty_returns_empty(project_env):
    result = run_clustering([], "2026-06-11")
    assert result == []
