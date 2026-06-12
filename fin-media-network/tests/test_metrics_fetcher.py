"""
MetricsFetcher testleri — tüm API istemcileri mock'lanır.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from src.db.database import reset_db
from src.feedback.metrics_fetcher import (
    MetricsFetcher,
    _tiktok_video_id,
    _twitter_tweet_id,
    _youtube_video_id,
)


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _seed_published(db, date_str: str, platform: str, publish_url: str) -> int:
    cid = db.insert_content({
        "date": date_str,
        "platform": platform,
        "title": "Test başlık",
        "body": "Test içerik. Bu içerik yatırım tavsiyesi değildir.",
        "word_count": 7,
        "compliance_passed": 1,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })
    db.execute(
        "UPDATE content SET published_at='2026-06-12 09:00:00', publish_url=? WHERE id=?",
        (publish_url, cid),
    )
    return cid


# ── URL çıkarma yardımcıları ──────────────────────────────────────────────────

class TestUrlParsers:
    def test_youtube_watch_url(self):
        assert _youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtube_short_url(self):
        assert _youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtube_invalid(self):
        assert _youtube_video_id("https://example.com") is None

    def test_tiktok_video_url(self):
        assert _tiktok_video_id("https://www.tiktok.com/@user/video/7123456789") == "7123456789"

    def test_tiktok_invalid(self):
        assert _tiktok_video_id("https://example.com") is None

    def test_twitter_status_url(self):
        assert _twitter_tweet_id("https://x.com/user/status/1234567890") == "1234567890"

    def test_twitter_old_domain(self):
        assert _twitter_tweet_id("https://twitter.com/user/status/999") == "999"

    def test_twitter_invalid(self):
        assert _twitter_tweet_id("https://example.com") is None


# ── YouTube metrikleri ────────────────────────────────────────────────────────

def _mock_youtube(views=1000, likes=50, comments=10):
    svc = MagicMock()
    svc.videos.return_value.list.return_value.execute.return_value = {
        "items": [{
            "statistics": {
                "viewCount": str(views),
                "likeCount": str(likes),
                "commentCount": str(comments),
            }
        }]
    }
    return svc


class TestYouTubeMetrics:
    def test_fetches_views_likes_comments(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_published(tmp_db, today, "youtube",
                              "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        fetcher = MetricsFetcher(youtube_service=_mock_youtube(2000, 80, 20))
        ids = fetcher.run(date.today())

        assert len(ids) == 1
        row = tmp_db.fetchone("SELECT * FROM performance WHERE id=?", (ids[0],))
        assert row["content_id"] == cid
        assert row["views"] == 2000
        assert row["likes"] == 80
        assert row["comments"] == 20
        assert row["platform"] == "youtube"

    def test_engagement_rate_calculated(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_published(tmp_db, today, "youtube",
                        "https://www.youtube.com/watch?v=abc1234defg")

        fetcher = MetricsFetcher(youtube_service=_mock_youtube(1000, 100, 50))
        ids = fetcher.run(date.today())

        row = tmp_db.fetchone("SELECT engagement_rate FROM performance WHERE id=?", (ids[0],))
        assert abs(row["engagement_rate"] - 0.15) < 1e-5

    def test_empty_items_skips_row(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_published(tmp_db, today, "youtube",
                        "https://www.youtube.com/watch?v=abc1234defg")

        svc = MagicMock()
        svc.videos.return_value.list.return_value.execute.return_value = {"items": []}
        fetcher = MetricsFetcher(youtube_service=svc)
        ids = fetcher.run(date.today())

        assert ids == []


# ── X / Twitter metrikleri ────────────────────────────────────────────────────

def _mock_x_client(impressions=500, likes=30, replies=5, retweets=10):
    client = MagicMock()
    tweet_mock = MagicMock()
    tweet_mock.data.public_metrics = {
        "impression_count": impressions,
        "like_count": likes,
        "reply_count": replies,
        "retweet_count": retweets,
    }
    client.get_tweet.return_value = tweet_mock
    return client


class TestXMetrics:
    def test_fetches_impressions_and_engagement(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_published(tmp_db, today, "x_thread",
                              "https://x.com/bistbot/status/1234567890")

        fetcher = MetricsFetcher(x_client=_mock_x_client(1000, 50, 10, 20))
        ids = fetcher.run(date.today())

        assert len(ids) == 1
        row = tmp_db.fetchone("SELECT * FROM performance WHERE id=?", (ids[0],))
        assert row["views"] == 1000
        assert row["likes"] == 50
        assert row["comments"] == 10
        assert row["shares"] == 20

    def test_x_engagement_rate(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_published(tmp_db, today, "x_thread",
                        "https://x.com/bistbot/status/999")

        fetcher = MetricsFetcher(x_client=_mock_x_client(1000, 100, 0, 0))
        ids = fetcher.run(date.today())

        row = tmp_db.fetchone("SELECT engagement_rate FROM performance WHERE id=?", (ids[0],))
        assert abs(row["engagement_rate"] - 0.1) < 1e-5


# ── TikTok metrikleri ─────────────────────────────────────────────────────────

def _mock_tiktok_session(views=3000, likes=200, comments=15, shares=40):
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {
        "data": {
            "videos": [{
                "view_count": views,
                "like_count": likes,
                "comment_count": comments,
                "share_count": shares,
            }]
        }
    }
    resp.raise_for_status = MagicMock()
    session.post.return_value = resp
    return session


class TestTikTokMetrics:
    def test_fetches_tiktok_metrics(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_published(tmp_db, today, "tiktok_1",
                              "https://www.tiktok.com/@bistbot/video/7777777777")

        fetcher = MetricsFetcher(tiktok_session=_mock_tiktok_session(5000, 300, 20, 50))
        ids = fetcher.run(date.today())

        assert len(ids) == 1
        row = tmp_db.fetchone("SELECT * FROM performance WHERE id=?", (ids[0],))
        assert row["views"] == 5000
        assert row["likes"] == 300
        assert row["platform"] == "tiktok_1"

    def test_all_four_tiktok_platforms(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        for i, plat in enumerate(("tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4"), start=1):
            _seed_published(tmp_db, today, plat,
                            f"https://www.tiktok.com/@bistbot/video/{i}000")

        fetcher = MetricsFetcher(tiktok_session=_mock_tiktok_session())
        ids = fetcher.run(date.today())
        assert len(ids) == 4


# ── Hata senaryoları ──────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_api_error_skips_and_continues(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_published(tmp_db, today, "youtube",
                        "https://www.youtube.com/watch?v=failfailfai")
        _seed_published(tmp_db, today, "x_thread",
                        "https://x.com/bistbot/status/123")

        bad_yt = MagicMock()
        bad_yt.videos.return_value.list.return_value.execute.side_effect = RuntimeError("quota")
        ok_x = _mock_x_client()
        fetcher = MetricsFetcher(youtube_service=bad_yt, x_client=ok_x)
        ids = fetcher.run(date.today())

        assert len(ids) == 1  # sadece X satırı eklendi

    def test_returns_empty_when_no_published(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        fetcher = MetricsFetcher(youtube_service=_mock_youtube())
        ids = fetcher.run(date.today())
        assert ids == []

    def test_invalid_url_skips_row(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_published(tmp_db, today, "youtube", "https://invalid-no-video-id.com")

        fetcher = MetricsFetcher(youtube_service=_mock_youtube())
        ids = fetcher.run(date.today())
        assert ids == []
