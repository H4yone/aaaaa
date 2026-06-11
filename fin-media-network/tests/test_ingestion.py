"""Gün 3 testi: rss_collector, kap_collector, normalizer."""
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"
_CONFIG = Path(__file__).parent.parent / "config"

from src.ingestion.rss_collector import (
    canonicalize_url,
    url_hash,
    parse_published,
    fetch_feed,
    save_to_db as rss_save_to_db,
)
from src.ingestion.kap_collector import (
    fetch_kap,
    _extract_ticker_from_title,
)
from src.processing.normalizer import (
    to_utc_str,
    utc_to_tr,
    get_source_weight,
    extract_tickers,
    normalize_row,
    normalize_batch,
)


# ── Yardımcı: feedparser mock ─────────────────────────────────────────────────

class _FeedEntry(dict):
    """feedparser FeedParserDict gibi hem dict hem attribute erişimi destekler."""
    def __getattr__(self, name):
        return self.get(name)


def _make_fake_feedparser_result(fixture_path: Path):
    fixture = json.loads(fixture_path.read_text())
    result = MagicMock()
    result.bozo = fixture["bozo"]
    result.entries = [_FeedEntry(e) for e in fixture["entries"]]
    return result


# ── settings.yaml gerektiren testlerde kullanılacak fixture ──────────────────

@pytest.fixture
def project_dir_env(tmp_path, monkeypatch):
    """tmp_path'e config kopyalayıp cwd'yi oraya ayarlar."""
    (tmp_path / "config").mkdir()
    for fname in ("settings.yaml", "source_weights.yaml"):
        shutil.copy(_CONFIG / fname, tmp_path / "config" / fname)
    monkeypatch.chdir(tmp_path)
    # normalizer cache sıfırla
    from src.processing import normalizer
    normalizer._SOURCE_WEIGHT_INDEX = {}
    return tmp_path


# ── rss_collector tests ───────────────────────────────────────────────────────

def test_canonicalize_url_removes_utm():
    url = "https://example.com/news?utm_source=google&utm_medium=rss&id=123"
    clean = canonicalize_url(url)
    assert "utm_source" not in clean
    assert "id=123" in clean


def test_canonicalize_url_lowercase_host():
    url = "HTTPS://Finance.Yahoo.Com/news/test"
    clean = canonicalize_url(url)
    assert clean.startswith("https://finance.yahoo.com")


def test_url_hash_deterministic():
    h1 = url_hash("https://example.com/news/1")
    h2 = url_hash("https://example.com/news/1")
    assert h1 == h2
    assert len(h1) == 32


def test_url_hash_utm_equivalent():
    url1 = "https://example.com/news?utm_source=rss"
    url2 = "https://example.com/news"
    assert url_hash(url1) == url_hash(url2)


def test_parse_published_from_parsed():
    entry = _FeedEntry({"published_parsed": (2026, 6, 11, 6, 0, 0, 3, 162, 0)})
    assert parse_published(entry) == "2026-06-11 06:00:00"


def test_parse_published_missing_returns_none():
    assert parse_published(_FeedEntry({})) is None


def test_fetch_feed_parses_entries(project_dir_env):
    fake = _make_fake_feedparser_result(_FIXTURES / "rss_feed_sample.json")
    with patch("feedparser.parse", return_value=fake):
        rows = fetch_feed("https://fake.feed/rss", "test_feed", 0.8)

    assert len(rows) == 3
    assert rows[0]["title"] == "Fed interest rate decision rocks global markets"
    assert rows[0]["feed_name"] == "test_feed"
    assert rows[0]["published_at"] == "2026-06-11 05:30:00"
    assert len(rows[0]["url_hash"]) == 32


def test_fetch_feed_deduplicates_url_hash(project_dir_env):
    """Aynı URL iki farklı feed'den gelirse url_hash aynı olmalı."""
    fake = _make_fake_feedparser_result(_FIXTURES / "rss_feed_sample.json")
    with patch("feedparser.parse", return_value=fake):
        rows1 = fetch_feed("https://feed1/rss", "feed1", 0.8)
        rows2 = fetch_feed("https://feed2/rss", "feed2", 0.8)

    hashes1 = {r["url_hash"] for r in rows1}
    hashes2 = {r["url_hash"] for r in rows2}
    assert hashes1 == hashes2


def test_rss_save_to_db(tmp_path):
    from src.db.database import reset_db
    db = reset_db(tmp_path / "test.db")
    db.init()

    rows = [
        {
            "url_hash": "h001",
            "url": "https://example.com/1",
            "title": "Test haber 1",
            "summary": None,
            "source_name": "example.com",
            "source_url": "https://example.com/rss",
            "published_at": "2026-06-11 06:00:00",
            "feed_name": "test",
            "raw_json": json.dumps({"source_weight": 0.8}),
        },
        {
            "url_hash": "h002",
            "url": "https://example.com/2",
            "title": "Test haber 2",
            "summary": "Özet",
            "source_name": "example.com",
            "source_url": "https://example.com/rss",
            "published_at": "2026-06-11 07:00:00",
            "feed_name": "test",
            "raw_json": None,
        },
    ]
    with patch("src.db.database.get_db", return_value=db):
        count = rss_save_to_db(rows)
    assert count == 2
    all_rows = db.fetchall("SELECT * FROM raw_news")
    assert len(all_rows) == 2


# ── kap_collector tests ───────────────────────────────────────────────────────

def test_extract_ticker_from_kap_title():
    assert _extract_ticker_from_title("GARAN - Garanti BBVA - Özel Durum") == "GARAN.IS"
    assert _extract_ticker_from_title("Türk Hava Yolları finansal tablolar") == "THYAO.IS"
    assert _extract_ticker_from_title("Tüpraş üretim raporu") == "TUPRS.IS"


def test_fetch_kap_parses_entries():
    fake = _make_fake_feedparser_result(_FIXTURES / "kap_feed_sample.json")
    with patch("feedparser.parse", return_value=fake):
        rows = fetch_kap()

    assert len(rows) == 2
    assert rows[0]["source_name"] == "kap.org.tr"
    assert rows[0]["feed_name"] == "kap_bildirimler"
    assert rows[0]["published_at"] == "2026-06-11 07:00:00"
    rj = json.loads(rows[0]["raw_json"])
    assert rj["source_weight"] == 1.0
    assert rj["category"] == "kap_disclosure"


def test_fetch_kap_network_error_returns_empty():
    with patch("feedparser.parse", side_effect=Exception("ağ hatası")):
        assert fetch_kap() == []


# ── normalizer tests ──────────────────────────────────────────────────────────

def test_to_utc_str_rfc2822():
    assert to_utc_str("Thu, 11 Jun 2026 06:00:00 GMT") == "2026-06-11 06:00:00"


def test_to_utc_str_iso():
    assert to_utc_str("2026-06-11T09:00:00+03:00") == "2026-06-11 06:00:00"


def test_to_utc_str_already_normalized():
    assert to_utc_str("2026-06-11 06:00:00") == "2026-06-11 06:00:00"


def test_to_utc_str_none():
    assert to_utc_str(None) is None


def test_utc_to_tr():
    assert utc_to_tr("2026-06-11 03:00:00") == "2026-06-11 06:00:00"


def test_get_source_weight_known_domain(project_dir_env):
    w = get_source_weight("https://www.reuters.com/article/test")
    assert w == 1.0


def test_get_source_weight_yahoo(project_dir_env):
    w = get_source_weight("https://finance.yahoo.com/news/test")
    assert w == 0.8


def test_get_source_weight_unknown_returns_low(project_dir_env):
    w = get_source_weight("https://somerandomsite.xyz/news")
    assert w < 0.6


def test_extract_tickers_bist():
    tickers = extract_tickers("Garanti Bankası ve BIST 100 endeksi yükseldi")
    assert "GARAN.IS" in tickers
    assert "XU100.IS" in tickers


def test_extract_tickers_global():
    tickers = extract_tickers("NVIDIA earnings beat lifts Nasdaq to new highs")
    assert "NVDA" in tickers
    assert "^NDX" in tickers


def test_extract_tickers_crypto():
    tickers = extract_tickers("Bitcoin rekor kırdı, BTC 70K üzerinde")
    assert "bitcoin" in tickers


def test_normalize_row(project_dir_env):
    row = {
        "url_hash": "x001",
        "url": "https://www.reuters.com/article/garanti",
        "title": "Garanti Bankası güçlü kâr açıkladı — BIST 100'ü takip edin",
        "summary": "GARAN.IS hisseleri %3 yükseldi",
        "source_name": "reuters.com",
        "source_url": "https://www.reuters.com/rss",
        "published_at": "Thu, 11 Jun 2026 06:30:00 GMT",
        "feed_name": "reuters_test",
        "raw_json": None,
    }
    result = normalize_row(row)
    assert result["published_at"] == "2026-06-11 06:30:00"
    rj = json.loads(result["raw_json"])
    assert rj["source_weight"] == 1.0
    assert "GARAN.IS" in rj["tickers_mentioned"]
    assert "XU100.IS" in rj["tickers_mentioned"]


def test_normalize_batch_processes_all():
    from src.processing import normalizer
    normalizer._SOURCE_WEIGHT_INDEX = {"example.com": 0.7}

    rows = [
        {
            "url_hash": f"h{i}",
            "url": f"https://example.com/{i}",
            "title": f"Haber {i}",
            "summary": None,
            "source_name": "example.com",
            "source_url": "https://example.com/rss",
            "published_at": "2026-06-11 06:00:00",
            "feed_name": "test",
            "raw_json": None,
        }
        for i in range(5)
    ]
    results = normalize_batch(rows)
    assert len(results) == 5
    for r in results:
        assert json.loads(r["raw_json"])["source_weight"] == 0.7
