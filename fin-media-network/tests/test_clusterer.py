"""
Clusterer testleri — benzerlik tabanlı kümeleme, DB fixture pattern.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from src.db.database import reset_db
from src.processing.clusterer import Clusterer


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch):
    """Test veritabanını sıfırlar, başlatır ve singleton'ı ayarlar."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    db = reset_db(db_path)
    db.init()
    return db


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def _seed_news(db, title: str, is_duplicate: int = 0, url: str | None = None) -> int:
    """raw_news tablosuna test satırı ekler, eklenen satırın ID'sini döner."""
    if url is None:
        url = f"http://example.com/{hashlib.md5(title.encode()).hexdigest()}"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    cursor = db.execute(
        "INSERT OR IGNORE INTO raw_news "
        "(url_hash, url, title, source_name, source_url, is_duplicate, fetched_at) "
        "VALUES (?,?,?,?,?,?,datetime('now'))",
        (url_hash, url, title, "test_source", url, is_duplicate),
    )
    last = cursor.lastrowid
    if last:
        return last
    row = db.fetchone("SELECT id FROM raw_news WHERE url_hash=?", (url_hash,))
    return row["id"]


# ── Testler ───────────────────────────────────────────────────────────────────

def test_returns_empty_when_no_news(tmp_db):
    """Veritabanı boşken küme oluşturulmaz, [] döner."""
    clusterer = Clusterer()
    result = clusterer.run(date.today())
    assert result == []


def test_single_article_creates_one_cluster(tmp_db):
    """Tek makale → tek küme ID'si döner."""
    _seed_news(tmp_db, "Fed politika faizini değiştirmedi")
    clusterer = Clusterer()
    result = clusterer.run(date.today())
    assert len(result) == 1


def test_similar_articles_merged(tmp_db):
    """Çok benzer iki başlık → tek kümede birleşir."""
    _seed_news(tmp_db, "Borsa İstanbul yüzde iki yükseldi", url="http://example.com/s1")
    # Aynı başlık ile URL hash çakışmasını önlemek için ayrı URL kullan
    url2 = "http://example.com/s2"
    url_hash2 = hashlib.sha256(url2.encode()).hexdigest()
    tmp_db.execute(
        "INSERT OR IGNORE INTO raw_news "
        "(url_hash, url, title, source_name, source_url, is_duplicate, fetched_at) "
        "VALUES (?,?,?,?,?,?,datetime('now'))",
        (url_hash2, url2, "Borsa İstanbul yüzde iki yükseldi bugün", "test_source", url2, 0),
    )
    clusterer = Clusterer(similarity_threshold=75)
    result = clusterer.run(date.today())
    # İki benzer başlık tek kümede birleşmeli
    assert len(result) == 1


def test_different_articles_separate_clusters(tmp_db):
    """Birbirinden farklı iki başlık → 2 ayrı küme oluşturulur."""
    _seed_news(tmp_db, "Altın rekor kırdı")
    _seed_news(tmp_db, "TCMB rezervleri artıyor")
    clusterer = Clusterer()
    result = clusterer.run(date.today())
    assert len(result) == 2


def test_cluster_count_recorded(tmp_db):
    """Küme news_count alanı, kümedeki makale sayısına eşit olur."""
    # Üç benzer başlık aynı kümede birleşmeli
    baslik_kok = "Dolar kuru tarihi zirvede"
    _seed_news(tmp_db, baslik_kok, url="http://example.com/cc1")
    url2 = "http://example.com/cc2"
    url3 = "http://example.com/cc3"
    for url, suffix in [(url2, " bugün"), (url3, " şimdi")]:
        tmp_db.execute(
            "INSERT OR IGNORE INTO raw_news "
            "(url_hash, url, title, source_name, source_url, is_duplicate, fetched_at) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (hashlib.sha256(url.encode()).hexdigest(), url, baslik_kok + suffix,
             "test_source", url, 0),
        )
    clusterer = Clusterer(similarity_threshold=75)
    result = clusterer.run(date.today())
    # En az bir küme oluşmuş olmalı
    assert len(result) >= 1
    cluster_id = result[0]
    row = tmp_db.fetchone("SELECT news_count FROM clusters WHERE id=?", (cluster_id,))
    assert row["news_count"] >= 1


def test_updates_cluster_id_in_raw_news(tmp_db):
    """run() sonrası raw_news.cluster_id alanı küme ID'siyle doldurulur."""
    article_id = _seed_news(tmp_db, "Enflasyon çift hanede kaldı")
    clusterer = Clusterer()
    cluster_ids = clusterer.run(date.today())
    assert len(cluster_ids) == 1
    row = tmp_db.fetchone("SELECT cluster_id FROM raw_news WHERE id=?", (article_id,))
    assert row["cluster_id"] == cluster_ids[0]


def test_skips_duplicates(tmp_db):
    """is_duplicate=1 makaleler kümelemeye dahil edilmez."""
    _seed_news(tmp_db, "Duplikat makale başlığı", is_duplicate=1)
    clusterer = Clusterer()
    result = clusterer.run(date.today())
    assert result == []


def test_skips_already_clustered(tmp_db):
    """Zaten cluster_id atanmış makaleler ikinci çalıştırmada atlanır."""
    _seed_news(tmp_db, "Önceden kümelenmiş haber")
    clusterer = Clusterer()
    # İlk çalıştırma — küme oluşturulur
    first_run = clusterer.run(date.today())
    assert len(first_run) == 1
    # İkinci çalıştırma — aynı makale zaten cluster_id'ye sahip, yeni küme açılmaz
    second_run = clusterer.run(date.today())
    assert second_run == []


def test_representative_title_is_first_article_title(tmp_db):
    """Kümenin representative_title'ı, kümedeki ilk makale başlığıdır."""
    ilk_baslik = "ABD borsaları rekor kırdı"
    _seed_news(tmp_db, ilk_baslik, url="http://example.com/rt1")
    # Benzer başlık ikinci sıraya ekle
    url2 = "http://example.com/rt2"
    tmp_db.execute(
        "INSERT OR IGNORE INTO raw_news "
        "(url_hash, url, title, source_name, source_url, is_duplicate, fetched_at) "
        "VALUES (?,?,?,?,?,?,datetime('now'))",
        (hashlib.sha256(url2.encode()).hexdigest(), url2, ilk_baslik + " bugün",
         "test_source", url2, 0),
    )
    clusterer = Clusterer(similarity_threshold=75)
    result = clusterer.run(date.today())
    assert len(result) >= 1
    cluster_id = result[0]
    row = tmp_db.fetchone(
        "SELECT representative_title FROM clusters WHERE id=?", (cluster_id,)
    )
    assert row["representative_title"] == ilk_baslik


def test_threshold_zero_everything_clusters(tmp_db):
    """Eşik 0 olduğunda tüm makaleler tek kümede toplanır."""
    _seed_news(tmp_db, "Haber başlığı birinci")
    _seed_news(tmp_db, "Bambaşka bir konu hakkında haber")
    _seed_news(tmp_db, "Üçüncü alakasız içerik")
    clusterer = Clusterer(similarity_threshold=0)
    result = clusterer.run(date.today())
    # Eşik sıfırda tüm makaleler ilk kümeyle eşleşir
    assert len(result) == 1
    row = tmp_db.fetchone("SELECT news_count FROM clusters WHERE id=?", (result[0],))
    assert row["news_count"] == 3
