"""
VideoGenerator testleri — ffmpeg subprocess'i mock runner ile.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.db.database import reset_db
from src.production.video_generator import VideoGenerator, _load_font, _wrap


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _seed_youtube(db, date_str: str, compliance_passed: int = 1) -> int:
    return db.insert_content({
        "date": date_str,
        "platform": "youtube",
        "title": "BIST analizi başlık",
        "body": "[SUNUCU] Merhaba. [ANALİST] Fed faizi sabit.",
        "word_count": 6,
        "compliance_passed": compliance_passed,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


def _ok_runner(creates_output: bool = True):
    """ffmpeg başarı taklidi — son argümandaki dosyayı yazar."""
    def runner(cmd, **kwargs):
        if creates_output:
            Path(cmd[-1]).write_bytes(b"fake_video")
        return MagicMock(returncode=0, stderr="")
    return runner


# ── Metin sarma ───────────────────────────────────────────────────────────────

class TestWrap:
    def test_wraps_long_text_into_multiple_lines(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("RGB", (100, 100)))
        font = _load_font(20)
        lines = _wrap(draw, "kelime " * 40, font, 200)
        assert len(lines) > 1

    def test_short_text_single_line(self):
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new("RGB", (100, 100)))
        font = _load_font(20)
        assert _wrap(draw, "kısa", font, 1000) == ["kısa"]


# ── Başlık kartı ──────────────────────────────────────────────────────────────

class TestTitleCard:
    def test_creates_png_with_correct_size(self, tmp_path):
        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=MagicMock())
        out = tmp_path / "card.png"
        vg.make_title_card("İran savaşı BIST'i etkiliyor " * 4, out)

        assert out.exists()
        from PIL import Image
        assert Image.open(out).size == (1920, 1080)


# ── MP4 render ────────────────────────────────────────────────────────────────

class TestRender:
    def test_builds_ffmpeg_command(self, tmp_path):
        runner = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
        vg = VideoGenerator(ffmpeg_exe="ffmpeg.exe", runner=runner)
        out = vg.render(tmp_path / "a.mp3", tmp_path / "c.png", tmp_path / "o.mp4")

        cmd = runner.call_args.args[0]
        assert cmd[0] == "ffmpeg.exe"
        assert str(tmp_path / "a.mp3") in cmd
        assert str(tmp_path / "c.png") in cmd
        assert cmd[-1] == str(tmp_path / "o.mp4")
        assert out == tmp_path / "o.mp4"

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        runner = MagicMock(return_value=MagicMock(returncode=1, stderr="boom"))
        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=runner)
        with pytest.raises(RuntimeError, match="ffmpeg"):
            vg.render(tmp_path / "a.mp3", tmp_path / "c.png", tmp_path / "o.mp4")


# ── Ana döngü ─────────────────────────────────────────────────────────────────

class TestRun:
    def test_generates_video_when_audio_exists(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_youtube(tmp_db, today)

        base = tmp_path / today
        base.mkdir(parents=True)
        (base / f"youtube_{cid}.mp3").write_bytes(b"audio")

        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=_ok_runner())
        paths = vg.run(date.today())

        assert len(paths) == 1
        assert paths[0].name == f"youtube_{cid}.mp4"
        assert paths[0].exists()

    def test_skips_when_no_audio(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        _seed_youtube(tmp_db, today)

        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=_ok_runner())
        assert vg.run(date.today()) == []

    def test_skips_when_video_exists(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_youtube(tmp_db, today)

        base = tmp_path / today
        base.mkdir(parents=True)
        (base / f"youtube_{cid}.mp3").write_bytes(b"audio")
        (base / f"youtube_{cid}.mp4").write_bytes(b"existing")

        runner = MagicMock()
        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=runner)
        assert vg.run(date.today()) == []
        runner.assert_not_called()

    def test_skips_noncompliant(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_youtube(tmp_db, today, compliance_passed=0)

        base = tmp_path / today
        base.mkdir(parents=True)
        (base / f"youtube_{cid}.mp3").write_bytes(b"audio")

        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=_ok_runner())
        assert vg.run(date.today()) == []

    def test_ffmpeg_error_skips_and_continues(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        cid = _seed_youtube(tmp_db, today)

        base = tmp_path / today
        base.mkdir(parents=True)
        (base / f"youtube_{cid}.mp3").write_bytes(b"audio")

        runner = MagicMock(return_value=MagicMock(returncode=1, stderr="boom"))
        vg = VideoGenerator(ffmpeg_exe="ffmpeg", runner=runner)
        assert vg.run(date.today()) == []
