"""
YouTubePublisher testleri — YouTube API ve DB mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import reset_db
from src.production.youtube_publisher import YouTubePublisher


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _seed_content(db, date_str: str, platform: str = "youtube",
                  compliance_passed: int = 1, human_approved: int = 1,
                  published_at=None) -> int:
    return db.insert_content({
        "date": date_str,
        "platform": platform,
        "title": "Fed Faiz Kararı ve BIST Analizi",
        "body": "Video içeriği buraya. Bu içerik yatırım tavsiyesi değildir.",
        "word_count": 10,
        "compliance_passed": compliance_passed,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


def _mock_service(video_id: str = "abc123") -> MagicMock:
    svc = MagicMock()
    insert_resp = MagicMock()
    insert_resp.execute.return_value = {"id": video_id}
    svc.videos.return_value.insert.return_value = insert_resp
    return svc


# ── Yükleme mantığı ───────────────────────────────────────────────────────────

class TestUploadVideo:
    def test_returns_youtube_url(self, tmp_path):
        svc = _mock_service("xyz789")
        publisher = YouTubePublisher(service=svc)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 16)

        url = publisher.upload_video("Test Başlık", "Açıklama", video,
                                     _media_upload_cls=MagicMock())
        assert url == "https://youtu.be/xyz789"

    def test_video_title_truncated_to_100(self, tmp_path):
        svc = _mock_service()
        publisher = YouTubePublisher(service=svc)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        long_title = "A" * 150

        publisher.upload_video(long_title, "desc", video,
                               _media_upload_cls=MagicMock())

        call_body = svc.videos.return_value.insert.call_args.kwargs["body"]
        assert len(call_body["snippet"]["title"]) <= 100


# ── Ana döngü ─────────────────────────────────────────────────────────────────

class TestYouTubePublisherRun:
    def test_returns_empty_when_no_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        publisher = YouTubePublisher(service=_mock_service())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_when_video_file_missing(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        publisher = YouTubePublisher(service=_mock_service())
        # OUTPUT_DIR'de video yok → atlanır
        monkeypatch.setenv("OUTPUT_DIR", "/nonexistent/path")
        ids = publisher.run(date.today())

        assert ids == []
        _mock_service().videos.return_value.insert.assert_not_called()

    def test_uploads_and_updates_db_when_video_exists(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        video_dir = tmp_path / today
        video_dir.mkdir(parents=True)
        (video_dir / f"youtube_{cid}.mp4").write_bytes(b"\x00" * 16)

        publisher = YouTubePublisher(service=_mock_service("vid001"))

        with patch.object(publisher, "upload_video", return_value="https://youtu.be/vid001"):
            ids = publisher.run(date.today())

        assert ids == [cid]
        row = tmp_db.fetchone("SELECT published_at, publish_url FROM content WHERE id=?", (cid,))
        assert row["publish_url"] == "https://youtu.be/vid001"
        assert row["published_at"] is not None

    def test_skips_not_approved_content(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today, human_approved=0)

        publisher = YouTubePublisher(service=_mock_service())
        ids = publisher.run(date.today())

        assert ids == []

    def test_skips_compliance_failed_content(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today, compliance_passed=0, human_approved=1)

        publisher = YouTubePublisher(service=_mock_service())
        ids = publisher.run(date.today())

        assert ids == []

    def test_skips_already_published(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today)
        tmp_db.execute(
            "UPDATE content SET human_approved=1, published_at='2026-06-12 10:00:00' WHERE id=?",
            (cid,),
        )

        publisher = YouTubePublisher(service=_mock_service())
        ids = publisher.run(date.today())

        assert ids == []

    def test_api_error_skips_content(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_content(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        video_dir = tmp_path / today
        video_dir.mkdir(parents=True)
        (video_dir / f"youtube_{cid}.mp4").write_bytes(b"\x00")

        publisher = YouTubePublisher(service=_mock_service())

        with patch.object(publisher, "upload_video", side_effect=RuntimeError("quota")):
            ids = publisher.run(date.today())

        assert ids == []
        row = tmp_db.fetchone("SELECT published_at FROM content WHERE id=?", (cid,))
        assert row["published_at"] is None
