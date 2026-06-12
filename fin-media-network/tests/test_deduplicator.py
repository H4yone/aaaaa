"""
Deduplicator testleri — rapidfuzz benzerlik eşiği, DB fixture pattern.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from src.db.database import reset_db
from src.processing.deduplicator import Deduplicator


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

def _seed_news(db, title: str, url: str | None = None) -> int:
    """raw_news tablosuna test satırı ekler, eklenen satırın ID'sini döner."""
    if url is None:
        url = f"http://example.com/{hashlib.md5(title.encode()).hexdigest()}"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    cursor = db.execute(
        "INSERT OR IGNORE INTO raw_news "
        "(url_hash, url, title, source_name, source_url, fetched_at) "
        "VALUES (?,?,?,?,?,datetime('now'))",
        (url_hash, url, title, "test_source", url),
    )
    last = cursor.lastrowid
    if last:
        return last
    # INSERT OR IGNORE sessizce atladıysa mevcut kaydın ID'sini sorgula
    row = db.fetchone("SELECT id FROM raw_news WHERE url_hash=?", (url_hash,))
    return row["id"]


# ── Testler ───────────────────────────────────────────────────────────────────

def test_returns_empty_when_no_news(tmp_db):
    """Veritabanı boşken [] döner."""
    dedup = Deduplicator()
    result = dedup.run(date.today())
    assert result == []


def test_no_duplicates_when_all_unique(tmp_db):
    """Birbirinden tamamen farklı 3 başlık → duplikat bulunamaz."""
    _seed_news(tmp_db, "Fed faiz kararı açıklandı")
    _seed_news(tmp_db, "Altın fiyatı rekor kırdı")
    _seed_news(tmp_db, "BIST 100 yeni zirveye ulaştı")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    assert result == []


def test_detects_exact_duplicate_title(tmp_db):
    """Tam aynı başlık ikinci kez eklendiğinde duplikat olarak tespit edilir."""
    baslik = "TCMB politika faizini sabit bıraktı"
    _seed_news(tmp_db, baslik, url="http://example.com/haber1")
    dup_id = _seed_news(tmp_db, baslik, url="http://example.com/haber2")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    assert dup_id in result


def test_detects_similar_title(tmp_db):
    """90+ benzerlik oranına sahip başlıklar duplikat olarak işaretlenir."""
    _seed_news(tmp_db, "Fed faiz artırdı", url="http://example.com/a1")
    dup_id = _seed_news(tmp_db, "Fed faizi artırdı!", url="http://example.com/a2")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    assert dup_id in result


def test_ignores_already_marked_duplicates(tmp_db):
    """is_duplicate=1 olarak işaretli satır yeniden işlenmez."""
    id1 = _seed_news(tmp_db, "Duplikat olarak önceden işaretlenmiş haber")
    # Manuel olarak duplikat işaretle
    tmp_db.execute("UPDATE raw_news SET is_duplicate=1 WHERE id=?", (id1,))
    dedup = Deduplicator()
    result = dedup.run(date.today())
    # Zaten işaretli satır sonuca dahil olmamalı
    assert id1 not in result


def test_threshold_custom_exact_only(tmp_db):
    """Eşik 100 olarak ayarlandığında yalnızca tam eşleşmeler duplikat sayılır."""
    _seed_news(tmp_db, "Borsa İstanbul güçlü kapandı", url="http://example.com/b1")
    # Benzer ama aynı değil — eşik 100'de duplikat sayılmamalı
    id_benzer = _seed_news(tmp_db, "Borsa İstanbul güçlü kapandı bugün", url="http://example.com/b2")
    # Tam aynı — eşik 100'de duplikat sayılmalı
    baslik_tam = "XU100 günlük kapanışta yüzde iki artı"
    _seed_news(tmp_db, baslik_tam, url="http://example.com/b3")
    id_tam_dup = _seed_news(tmp_db, baslik_tam, url="http://example.com/b4")

    dedup = Deduplicator(threshold=100)
    result = dedup.run(date.today())
    assert id_benzer not in result
    assert id_tam_dup in result


def test_first_article_kept_not_marked(tmp_db):
    """İki benzer makaleden ilk eklenen duplikat olarak işaretlenmez."""
    id_ilk = _seed_news(tmp_db, "Enflasyon verileri beklentileri aştı", url="http://example.com/c1")
    _seed_news(tmp_db, "Enflasyon verileri beklentileri aştı!", url="http://example.com/c2")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    # İlk makale duplikat listesinde olmamalı
    assert id_ilk not in result


def test_returns_duplicate_ids(tmp_db):
    """Dönüş değeri duplikat olarak işaretlenen satır ID'lerini içerir."""
    baslik = "Dolar kuru güne artışla başladı"
    _seed_news(tmp_db, baslik, url="http://example.com/d1")
    id2 = _seed_news(tmp_db, baslik, url="http://example.com/d2")
    id3 = _seed_news(tmp_db, baslik, url="http://example.com/d3")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    # Her iki kopyanın ID'si de sonuçta olmalı
    assert id2 in result
    assert id3 in result


def test_marks_db_correctly(tmp_db):
    """run() sonrası duplikat satırların raw_news.is_duplicate=1 olduğu doğrulanır."""
    baslik = "Petrol fiyatları yüzde üç geriledi"
    _seed_news(tmp_db, baslik, url="http://example.com/e1")
    dup_id = _seed_news(tmp_db, baslik, url="http://example.com/e2")
    dedup = Deduplicator()
    dedup.run(date.today())
    row = tmp_db.fetchone("SELECT is_duplicate FROM raw_news WHERE id=?", (dup_id,))
    assert row["is_duplicate"] == 1


def test_below_threshold_not_marked(tmp_db):
    """Benzerlik eşiğinin altındaki başlıklar duplikat sayılmaz."""
    _seed_news(tmp_db, "Fed faiz kararı beklentilerle örtüştü", url="http://example.com/f1")
    # Tamamen farklı başlık — duplikat olmamalı
    id2 = _seed_news(tmp_db, "Altın ons fiyatı yükseliyor", url="http://example.com/f2")
    dedup = Deduplicator()
    result = dedup.run(date.today())
    assert id2 not in result
