"""
RSSFetcher testleri — feedparser mocklıdır, DB geçici dizinde.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.db.database import reset_db
from src.ingestion.rss_fetcher import RSSFetcher


# ── Yardımcı sabitler ────────────────────────────────────────────────────────

_SETTINGS = {
    "pipeline": {"daily_run_hour": 6, "evening_run_hour": 18, "timezone": "UTC"},
    "rss_feeds": {
        "test_feed": [
            {"url": "http://test.feed/rss", "name": "test_feed", "weight": 0.8}
        ]
    },
}

_WEIGHTS = {
    "tier_elite": {"weight": 1.0, "sources": ["reuters.com"]},
    "tier_high": {"weight": 0.9, "sources": ["cnbc.com"]},
    "tier_medium": {"weight": 0.8, "sources": ["yahoo.com"]},
    "tier_low": {"weight": 0.5, "sources": ["reddit.com"]},
    "tier_unknown": {"weight": 0.4},
}


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Geçici config dosyaları oluşturur ve dizin yolunu döner."""
    settings_path = tmp_path / "settings.yaml"
    weights_path = tmp_path / "source_weights.yaml"
    settings_path.write_text(yaml.dump(_SETTINGS), encoding="utf-8")
    weights_path.write_text(yaml.dump(_WEIGHTS), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch):
    """Test veritabanını sıfırlar, başlatır ve singleton'ı ayarlar."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    db = reset_db(db_path)
    db.init()
    return db


def _make_fetcher(config_dir: Path, feedparser_mock: MagicMock | None = None) -> RSSFetcher:
    """Verilen config dizini ve opsiyonel feedparser mock'u ile RSSFetcher oluşturur."""
    return RSSFetcher(
        config_path=config_dir / "settings.yaml",
        source_weights_path=config_dir / "source_weights.yaml",
        feedparser_module=feedparser_mock,
    )


def _make_entry(
    title: str = "Test Haberi",
    link: str = "http://example.com/haber/1",
    summary: str = "Özet metin",
    published_parsed=None,
) -> MagicMock:
    """feedparser girdisini temsil eden MagicMock döner."""
    entry = MagicMock()
    entry.get.side_effect = lambda key, default=None: {
        "title": title,
        "link": link,
        "summary": summary,
        "published_parsed": published_parsed,
    }.get(key, default)
    # source attribute için None döner (feedparser source alanı)
    entry.source = None
    return entry


def _make_feedparser_mock(entries: list) -> MagicMock:
    """Belirtilen girdileri dönen feedparser modülü mock'u oluşturur."""
    fp = MagicMock()
    parsed = MagicMock()
    parsed.get.side_effect = lambda key, default=None: {
        "entries": entries,
    }.get(key, default)
    fp.parse.return_value = parsed
    return fp


# ── TestUrlHash ───────────────────────────────────────────────────────────────

class TestUrlHash:
    def test_hash_is_sha256_hex(self, config_dir: Path):
        """URL hash'inin sha256 hex formatında 64 karakter olduğu doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        result = fetcher._url_hash("http://example.com/haber")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_urls_produce_different_hashes(self, config_dir: Path):
        """Farklı URL'lerin farklı hash ürettiği doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        h1 = fetcher._url_hash("http://example.com/haber/1")
        h2 = fetcher._url_hash("http://example.com/haber/2")
        assert h1 != h2

    def test_same_url_same_hash(self, config_dir: Path):
        """Aynı URL'nin her seferinde aynı hash ürettiği doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        url = "http://example.com/tekrar"
        assert fetcher._url_hash(url) == fetcher._url_hash(url)

    def test_hash_matches_manual_sha256(self, config_dir: Path):
        """Üretilen hash'in elle hesaplanan sha256 ile örtüştüğü doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        url = "http://reuters.com/article/123"
        expected = hashlib.sha256(url.encode()).hexdigest()
        assert fetcher._url_hash(url) == expected


# ── TestSourceWeight ──────────────────────────────────────────────────────────

class TestSourceWeight:
    def test_reuters_returns_elite_weight(self, config_dir: Path):
        """reuters.com kaynağının 1.0 ağırlık aldığı doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        assert fetcher._source_weight("https://reuters.com/article/1") == 1.0

    def test_cnbc_returns_high_weight(self, config_dir: Path):
        """cnbc.com kaynağının 0.9 ağırlık aldığı doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        assert fetcher._source_weight("https://cnbc.com/market/1") == 0.9

    def test_yahoo_returns_medium_weight(self, config_dir: Path):
        """yahoo.com kaynağının 0.8 ağırlık aldığı doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        assert fetcher._source_weight("https://yahoo.com/finance") == 0.8

    def test_reddit_returns_low_weight(self, config_dir: Path):
        """reddit.com kaynağının 0.5 ağırlık aldığı doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        assert fetcher._source_weight("https://reddit.com/r/investing/post") == 0.5

    def test_unknown_domain_returns_default_weight(self, config_dir: Path):
        """Bilinmeyen domain'in 0.4 varsayılan ağırlık aldığı doğrulanır."""
        fetcher = _make_fetcher(config_dir)
        assert fetcher._source_weight("https://unknown-site.xyz/news") == 0.4


# ── TestParseEntry ────────────────────────────────────────────────────────────

class TestParseEntry:
    def test_valid_entry_returns_all_keys(self, config_dir: Path):
        """Geçerli girdi tüm zorunlu anahtarları içeren dict döner."""
        fetcher = _make_fetcher(config_dir)
        entry = _make_entry()
        result = fetcher._parse_entry(entry, "test_feed", 0.8)
        assert result is not None
        for key in ("url_hash", "url", "title", "summary", "source_name",
                    "source_url", "published_at", "feed_name", "raw_json"):
            assert key in result

    def test_no_title_returns_none(self, config_dir: Path):
        """Başlıksız girdi None döner."""
        fetcher = _make_fetcher(config_dir)
        entry = _make_entry(title="")
        result = fetcher._parse_entry(entry, "test_feed", 0.8)
        assert result is None

    def test_no_link_returns_none(self, config_dir: Path):
        """Linksiz girdi None döner."""
        fetcher = _make_fetcher(config_dir)
        entry = _make_entry(link="")
        result = fetcher._parse_entry(entry, "test_feed", 0.8)
        assert result is None

    def test_no_published_parsed_gives_none_published_at(self, config_dir: Path):
        """published_parsed=None ise published_at alanı None olur."""
        fetcher = _make_fetcher(config_dir)
        entry = _make_entry(published_parsed=None)
        result = fetcher._parse_entry(entry, "test_feed", 0.8)
        assert result is not None
        assert result["published_at"] is None

    def test_published_parsed_sets_published_at(self, config_dir: Path):
        """published_parsed değeri verildiğinde published_at ISO formatında dolar."""
        fetcher = _make_fetcher(config_dir)
        # (yıl, ay, gün, saat, dakika, saniye) tuple'ı
        entry = _make_entry(published_parsed=(2026, 6, 12, 10, 0, 0))
        result = fetcher._parse_entry(entry, "test_feed", 0.8)
        assert result is not None
        assert result["published_at"] is not None
        assert "2026-06-12" in result["published_at"]


# ── TestRSSFetcherRun ─────────────────────────────────────────────────────────

class TestRSSFetcherRun:
    def test_inserts_new_articles(self, config_dir: Path, tmp_db, monkeypatch):
        """Feedparser 2 girdi döndürdüğünde 2 ID eklenir."""
        entries = [
            _make_entry(title="Haber 1", link="http://example.com/1"),
            _make_entry(title="Haber 2", link="http://example.com/2"),
        ]
        fp = _make_feedparser_mock(entries)
        fetcher = _make_fetcher(config_dir, feedparser_mock=fp)
        ids = fetcher.run()
        assert len(ids) == 2
        assert all(isinstance(i, int) and i > 0 for i in ids)

    def test_skips_duplicate_url(self, config_dir: Path, tmp_db, monkeypatch):
        """Aynı URL iki kez feedparser'dan geldiğinde ikincisi eklenmez."""
        entry = _make_entry(title="Tekrar Haber", link="http://example.com/tekrar")
        fp = _make_feedparser_mock([entry])
        fetcher = _make_fetcher(config_dir, feedparser_mock=fp)

        # İlk çalıştırma — eklenir
        first_ids = fetcher.run()
        assert len(first_ids) == 1

        # İkinci çalıştırma — duplikat, eklenmez
        second_ids = fetcher.run()
        assert len(second_ids) == 0

    def test_feedparser_error_skips_feed(self, config_dir: Path, tmp_db, monkeypatch):
        """Feedparser istisna fırlatırsa feed atlanır ve [] döner."""
        fp = MagicMock()
        fp.parse.side_effect = Exception("Ağ hatası")
        fetcher = _make_fetcher(config_dir, feedparser_mock=fp)
        result = fetcher.run()
        assert result == []

    def test_returns_empty_when_no_feeds(self, tmp_path: Path, monkeypatch):
        """rss_feeds boş olduğunda [] döner."""
        db_path = tmp_path / "test.db"
        monkeypatch.setenv("DB_PATH", str(db_path))
        db = reset_db(db_path)
        db.init()

        # rss_feeds boş settings
        empty_settings = {
            "pipeline": {"daily_run_hour": 6, "evening_run_hour": 18, "timezone": "UTC"},
            "rss_feeds": {},
        }
        settings_path = tmp_path / "settings_empty.yaml"
        weights_path = tmp_path / "source_weights.yaml"
        settings_path.write_text(yaml.dump(empty_settings), encoding="utf-8")
        weights_path.write_text(yaml.dump(_WEIGHTS), encoding="utf-8")

        fetcher = RSSFetcher(
            config_path=settings_path,
            source_weights_path=weights_path,
            feedparser_module=MagicMock(),
        )
        result = fetcher.run()
        assert result == []
