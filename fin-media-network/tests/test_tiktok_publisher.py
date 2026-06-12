"""
TikTokPublisher testleri — requests.Session mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.db.database import reset_db
from src.production.tiktok_publisher import TikTokPublisher


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _mock_session(publish_id: str = "tt_vid_001") -> MagicMock:
    session = MagicMock()

    # POST /init/ yanıtı
    init_resp = MagicMock()
    init_resp.json.return_value = {
        "data": {
            "upload_url": "https://upload.tiktok.test/chunk",
            "publish_id": publish_id,
        }
    }
    init_resp.raise_for_status = MagicMock()

    # PUT upload yanıtı
    upload_resp = MagicMock()
    upload_resp.raise_for_status = MagicMock()

    session.post.return_value = init_resp
    session.put.return_value = upload_resp
    return session


def _seed_tiktok(db, date_str: str, platform: str = "tiktok_1",
                 compliance_passed: int = 1, human_approved: int = 1) -> int:
    return db.insert_content({
        "date": date_str,
        "platform": platform,
        "title": "Fed faiz analizi — kısa",
        "body": "Fed faizi artırdı! Bu içerik yatırım tavsiyesi değildir.",
        "word_count": 8,
        "compliance_passed": compliance_passed,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


# ── Video yükleme ─────────────────────────────────────────────────────────────

class TestUploadVideo:
    def test_returns_tiktok_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "myapp")
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 32)

        publisher = TikTokPublisher(session=_mock_session("99999"))

        with patch.object(publisher, "_init_upload",
                          return_value={"upload_url": "http://up", "publish_id": "99999"}):
            with patch.object(publisher, "_upload_chunk"):
                url = publisher.upload_video("Test Video", video)

        assert "99999" in url
        assert "tiktok.com" in url

    def test_title_truncated_to_150(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "app")
        publisher = TikTokPublisher(session=_mock_session())
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")
        long_title = "B" * 200

        publisher._init_upload(long_title, 1)

        payload = publisher._session.post.call_args.kwargs.get("json") or \
                  publisher._session.post.call_args.args[1] if \
                  publisher._session.post.call_args.args else \
                  publisher._session.post.call_args[1].get("json", {})
        # POST'un json parametresindeki title kontrolü
        posted = publisher._session.post.call_args.kwargs.get("json", {})
        assert len(posted.get("post_info", {}).get("title", long_title)) <= 150


# ── Ana döngü ─────────────────────────────────────────────────────────────────

class TestTikTokPublisherRun:
    def test_returns_empty_when_no_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        publisher = TikTokPublisher(session=_mock_session())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_when_video_missing(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_tiktok(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        publisher = TikTokPublisher(session=_mock_session())
        ids = publisher.run(date.today())
        assert ids == []

    def test_uploads_and_updates_db(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "bistbot")
        today = date.today().isoformat()
        cid = _seed_tiktok(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        video_dir = tmp_path / today
        video_dir.mkdir(parents=True)
        (video_dir / f"tiktok_1_{cid}.mp4").write_bytes(b"\x00" * 64)

        publisher = TikTokPublisher(session=_mock_session("vid123"))

        with patch.object(publisher, "upload_video",
                          return_value="https://www.tiktok.com/@bistbot/video/vid123"):
            ids = publisher.run(date.today())

        assert ids == [cid]
        row = tmp_db.fetchone("SELECT published_at, publish_url FROM content WHERE id=?", (cid,))
        assert "vid123" in row["publish_url"]
        assert row["published_at"] is not None

    def test_skips_unapproved(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        _seed_tiktok(tmp_db, today, human_approved=0)

        publisher = TikTokPublisher(session=_mock_session())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_compliance_failed(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        _seed_tiktok(tmp_db, today, compliance_passed=0, human_approved=1)

        publisher = TikTokPublisher(session=_mock_session())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_already_published(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_tiktok(tmp_db, today)
        tmp_db.execute(
            "UPDATE content SET human_approved=1, published_at='2026-06-12 09:00:00' WHERE id=?",
            (cid,),
        )

        publisher = TikTokPublisher(session=_mock_session())
        ids = publisher.run(date.today())
        assert ids == []

    def test_api_error_skips_and_continues(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "u")
        today = date.today().isoformat()
        cid1 = _seed_tiktok(tmp_db, today, "tiktok_1")
        cid2 = _seed_tiktok(tmp_db, today, "tiktok_2")
        for cid in (cid1, cid2):
            tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        video_dir = tmp_path / today
        video_dir.mkdir(parents=True)
        for cid, platform in ((cid1, "tiktok_1"), (cid2, "tiktok_2")):
            (video_dir / f"{platform}_{cid}.mp4").write_bytes(b"\x00")

        publisher = TikTokPublisher(session=_mock_session())
        publisher.upload_video = MagicMock(side_effect=[
            RuntimeError("upload hatası"),
            "https://www.tiktok.com/@u/video/999",
        ])
        ids = publisher.run(date.today())

        assert cid1 not in ids
        assert cid2 in ids

    def test_all_four_tiktok_platforms_queried(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("TIKTOK_CLIENT_KEY", "u")
        today = date.today().isoformat()

        video_dir = tmp_path / today
        video_dir.mkdir(parents=True)

        cids = []
        for platform in ("tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4"):
            cid = _seed_tiktok(tmp_db, today, platform)
            tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))
            (video_dir / f"{platform}_{cid}.mp4").write_bytes(b"\x00")
            cids.append(cid)

        publisher = TikTokPublisher(session=_mock_session())
        publisher.upload_video = MagicMock(
            return_value="https://www.tiktok.com/@u/video/1"
        )
        ids = publisher.run(date.today())

        assert len(ids) == 4
