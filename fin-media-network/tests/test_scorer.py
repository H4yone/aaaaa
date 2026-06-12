"""
Scorer testleri — puan hesaplama, tier atama, DB fixture pattern.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from src.db.database import reset_db
from src.processing.scorer import Scorer


# ── Config içerikleri ─────────────────────────────────────────────────────────

_SETTINGS = {
    "pipeline": {"daily_run_hour": 6, "timezone": "UTC"},
    "scoring": {
        "tier1_threshold": 70,
        "tier2_min": 40,
    },
}

_WEIGHTS = {
    "tier_elite": {"weight": 1.0, "sources": ["reuters.com"]},
    "tier_high": {"weight": 0.9, "sources": ["cnbc.com"]},
    "tier_medium": {"weight": 0.8, "sources": ["yahoo.com"]},
    "tier_low": {"weight": 0.5, "sources": ["reddit.com"]},
    "tier_unknown": {"weight": 0.4},
}

_MATRIX = {
    "rules": [
        {
            "id": "fed_hawkish",
            "keywords": ["hawkish", "rate hike", "faiz artışı", "tighten", "10Y", "treasury yield"],
        },
        {
            "id": "fed_dovish",
            "keywords": ["dovish", "rate cut", "faiz indirimi", "pivot", "easing"],
        },
    ]
}


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture()
def config_files(tmp_path: Path):
    """Geçici config dosyalarını oluşturur, yollarını dict olarak döner."""
    settings_path = tmp_path / "settings.yaml"
    weights_path = tmp_path / "source_weights.yaml"
    matrix_path = tmp_path / "transmission_matrix.yaml"
    settings_path.write_text(yaml.dump(_SETTINGS), encoding="utf-8")
    weights_path.write_text(yaml.dump(_WEIGHTS), encoding="utf-8")
    matrix_path.write_text(yaml.dump(_MATRIX), encoding="utf-8")
    return {
        "settings": settings_path,
        "weights": weights_path,
        "matrix": matrix_path,
    }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch):
    """Test veritabanını sıfırlar, başlatır ve singleton'ı ayarlar."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    db = reset_db(db_path)
    db.init()
    return db


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def _make_scorer(config_files: dict) -> Scorer:
    """Config dosyalarıyla Scorer örneği oluşturur."""
    return Scorer(
        config_path=config_files["settings"],
        source_weights_path=config_files["weights"],
        matrix_path=config_files["matrix"],
    )


def _seed_cluster(db, title: str, date_str: str, news_count: int = 1) -> int:
    """clusters tablosuna sıfır puanlı test kümesi ekler, ID'yi döner."""
    cursor = db.execute(
        "INSERT INTO clusters "
        "(date, representative_title, news_count, source_weight, "
        "market_relevance, volatility_impact, score, keywords, tickers_mentioned) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (date_str, title, news_count, 0.0, 0.0, 0.0, 0.0,
         json.dumps([]), json.dumps([])),
    )
    return cursor.lastrowid


def _seed_news_for_cluster(db, cluster_id: int, source_url: str = "http://unknown.xyz") -> int:
    """raw_news tablosuna kümeye bağlı test satırı ekler, ID'yi döner."""
    url = f"{source_url}/article/{cluster_id}"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    cursor = db.execute(
        "INSERT OR IGNORE INTO raw_news "
        "(url_hash, url, title, source_name, source_url, cluster_id, fetched_at) "
        "VALUES (?,?,?,?,?,?,datetime('now'))",
        (url_hash, url, "Test haber", "test_source", source_url, cluster_id),
    )
    last = cursor.lastrowid
    if last:
        return last
    row = db.fetchone("SELECT id FROM raw_news WHERE url_hash=?", (url_hash,))
    return row["id"]


# ── Birim testleri: _market_relevance ────────────────────────────────────────

def test_market_relevance_zero_for_unknown_title(config_files):
    """Piyasayla alakasız genel başlık için ilgililik skoru sıfır döner."""
    scorer = _make_scorer(config_files)
    # Transmission matrix'te geçmeyen tamamen genel bir başlık
    relevance = scorer._market_relevance("Bugün hava güneşli")
    assert relevance == 0.0


def test_market_relevance_high_for_keyword_match(config_files):
    """Transmission matrix anahtar kelimelerini içeren başlık yüksek ilgililik skoruna sahiptir."""
    scorer = _make_scorer(config_files)
    # "hawkish" ve "rate hike" → 2 eşleşme → 1.0
    relevance = scorer._market_relevance("Fed hawkish rate hike beklentisi arttı")
    assert relevance == 1.0


# ── Birim testleri: _volatility_impact ───────────────────────────────────────

def test_volatility_impact_faiz_keyword(config_files):
    """'faiz' anahtar kelimesini içeren başlık 1.0 volatilite etkisi verir."""
    scorer = _make_scorer(config_files)
    impact = scorer._volatility_impact("TCMB faiz kararı açıklandı")
    assert impact == 1.0


def test_volatility_impact_default_for_generic(config_files):
    """Hiçbir volatilite kategorisine uymayan başlık 0.2 varsayılan etkisi alır."""
    scorer = _make_scorer(config_files)
    impact = scorer._volatility_impact("Borsa haberleri günlük özet")
    assert impact == 0.2


# ── Entegrasyon testleri: run() ───────────────────────────────────────────────

def test_run_scores_cluster(config_files, tmp_db, monkeypatch):
    """reuters.com kaynaklı küme run() sonrası sıfırdan büyük skor alır."""
    tarih = date.today().isoformat()
    cluster_id = _seed_cluster(tmp_db, "Fed faiz kararı piyasaları sarstı", tarih)
    _seed_news_for_cluster(tmp_db, cluster_id, source_url="https://reuters.com")
    scorer = _make_scorer(config_files)
    scorer.run(date.today())
    row = tmp_db.fetchone("SELECT score FROM clusters WHERE id=?", (cluster_id,))
    assert row["score"] > 0.0


def test_tier1_assigned_when_score_high(config_files, tmp_db, monkeypatch):
    """Yüksek puan koşulları sağlandığında kümeye tier=1 atanır."""
    tarih = date.today().isoformat()
    # Hawkish + rate hike → market_relevance=1.0; faiz → vol=1.0; reuters → source=1.0
    title = "Fed hawkish rate hike faiz kararı açıklandı"
    cluster_id = _seed_cluster(tmp_db, title, tarih, news_count=3)
    _seed_news_for_cluster(tmp_db, cluster_id, source_url="https://reuters.com")
    scorer = _make_scorer(config_files)
    scorer.run(date.today())
    row = tmp_db.fetchone("SELECT tier, score FROM clusters WHERE id=?", (cluster_id,))
    assert row["tier"] == 1
    assert row["score"] >= 70


def test_tier2_assigned_for_mid_score(config_files, tmp_db, monkeypatch):
    """Orta aralık puan → tier=2 atanır."""
    tarih = date.today().isoformat()
    # Bilinmeyen kaynak (0.4) + bir eşleşme (0.5 relevance) + düşük volatilite (0.2)
    # ham_skor = (0.4*0.4 + 0.35*0.5 + 0.25*0.2) * 100 = (0.16+0.175+0.05)*100 = 38.5 < 40
    # Biraz daha yüksek volatilite: earnings → 0.9
    title = "Şirket earnings açıklaması hawkish beklenti ile çakıştı"
    cluster_id = _seed_cluster(tmp_db, title, tarih, news_count=1)
    _seed_news_for_cluster(tmp_db, cluster_id, source_url="https://unknown-news.xyz")
    scorer = _make_scorer(config_files)
    scorer.run(date.today())
    row = tmp_db.fetchone("SELECT tier, score FROM clusters WHERE id=?", (cluster_id,))
    # Puan hesapla: source=0.4, relevance=0.5 (hawkish eşleşir), vol=0.9 (earnings)
    # raw = (0.4*0.4 + 0.35*0.5 + 0.25*0.9)*100 = (0.16+0.175+0.225)*100 = 56.0 → tier2
    assert row["tier"] == 2
    assert 40 <= row["score"] < 70


def test_no_tier_for_low_score(config_files, tmp_db, monkeypatch):
    """Düşük puanlı küme için tier NULL kalır."""
    tarih = date.today().isoformat()
    # Bilinmeyen kaynak (0.4) + alakasız başlık (0 relevance) + genel (0.2 vol)
    # ham_skor = (0.4*0.4 + 0.35*0 + 0.25*0.2)*100 = (0.16+0+0.05)*100 = 21.0 < 40
    title = "Günlük hava durumu raporu"
    cluster_id = _seed_cluster(tmp_db, title, tarih)
    _seed_news_for_cluster(tmp_db, cluster_id, source_url="https://unknown-blog.net")
    scorer = _make_scorer(config_files)
    scorer.run(date.today())
    row = tmp_db.fetchone("SELECT tier FROM clusters WHERE id=?", (cluster_id,))
    assert row["tier"] is None


def test_returns_tiered_cluster_ids_only(config_files, tmp_db, monkeypatch):
    """run() dönüş değeri yalnızca tier 1 veya tier 2 küme ID'lerini içerir."""
    tarih = date.today().isoformat()
    # Tier alacak küme — yüksek puan
    title_high = "Fed hawkish rate hike faiz kararı büyük sürpriz"
    id_yuksek = _seed_cluster(tmp_db, title_high, tarih, news_count=2)
    _seed_news_for_cluster(tmp_db, id_yuksek, source_url="https://reuters.com")
    # Tier almayacak küme — düşük puan
    title_low = "Bugün güneşli hava bekleniyor"
    id_dusuk = _seed_cluster(tmp_db, title_low, tarih)
    _seed_news_for_cluster(tmp_db, id_dusuk, source_url="https://unknown-xyz.net")
    scorer = _make_scorer(config_files)
    result = scorer.run(date.today())
    assert id_yuksek in result
    assert id_dusuk not in result


def test_skips_already_scored(config_files, tmp_db, monkeypatch):
    """Daha önce puanlanmış (score > 0) kümeler yeniden işlenmez."""
    tarih = date.today().isoformat()
    cluster_id = _seed_cluster(tmp_db, "Önceden puanlanmış haber", tarih)
    # Skoru manuel olarak sıfırdan büyük yap
    tmp_db.execute(
        "UPDATE clusters SET score=55.0, tier=2 WHERE id=?", (cluster_id,)
    )
    scorer = _make_scorer(config_files)
    result = scorer.run(date.today())
    # Zaten puanlı küme tekrar işlenmemeli — result'a dahil olmamalı
    assert cluster_id not in result
    # DB'deki değer değişmemeli
    row = tmp_db.fetchone("SELECT score FROM clusters WHERE id=?", (cluster_id,))
    assert row["score"] == 55.0
