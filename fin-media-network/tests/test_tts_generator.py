"""
TTSGenerator testleri — ElevenLabs client mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from src.db.database import reset_db
from src.production.tts_generator import TTSGenerator


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _mock_elevenlabs_client(chunks: list[bytes] | None = None) -> MagicMock:
    """Ses verisi olarak byte chunk'lar dönen mock ElevenLabs client."""
    if chunks is None:
        chunks = [b"audio_chunk_1", b"audio_chunk_2"]
    client = MagicMock()
    client.text_to_speech.convert.return_value = iter(chunks)
    return client


def _seed_tiktok_content(db, date_str: str, platform: str = "tiktok_1") -> int:
    return db.insert_content({
        "date": date_str,
        "platform": platform,
        "title": "Fed analizi TikTok",
        "body": "Fed faizi artırdı. BIST sert düştü. Bu içerik yatırım tavsiyesi değildir.",
        "word_count": 10,
        "compliance_passed": 1,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


# ── Tek ses üretimi ────────────────────────────────────────────────────────────

class TestTTSGenerate:
    def test_creates_mp3_file(self, tmp_path):
        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        out = tmp_path / "test.mp3"

        result = gen.generate("Merhaba dünya", out, voice_id="voice_abc")

        assert result == out
        assert out.exists()
        assert out.read_bytes() == b"audio_chunk_1audio_chunk_2"

    def test_uses_provided_voice_id(self, tmp_path):
        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        out = tmp_path / "test.mp3"

        gen.generate("Test", out, voice_id="my_voice_id")

        client.text_to_speech.convert.assert_called_once()
        call_kwargs = client.text_to_speech.convert.call_args.kwargs
        assert call_kwargs["voice_id"] == "my_voice_id"

    def test_uses_env_voice_id_when_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_VOICE_ID_DENIZ", "deniz_voice_123")
        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        out = tmp_path / "test.mp3"

        gen.generate("Test", out)

        call_kwargs = client.text_to_speech.convert.call_args.kwargs
        assert call_kwargs["voice_id"] == "deniz_voice_123"

    def test_creates_parent_directories(self, tmp_path):
        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        nested = tmp_path / "a" / "b" / "c" / "out.mp3"

        gen.generate("Test", nested, voice_id="v")
        assert nested.exists()

    def test_api_error_propagates(self, tmp_path):
        client = MagicMock()
        client.text_to_speech.convert.side_effect = RuntimeError("API hatası")
        gen = TTSGenerator(client=client)

        with pytest.raises(RuntimeError, match="API hatası"):
            gen.generate("Test", tmp_path / "out.mp3", voice_id="v")


# ── Toplu üretim ──────────────────────────────────────────────────────────────

class TestTTSRun:
    def test_generates_for_all_tiktok_platforms(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("ELEVENLABS_VOICE_ID_MERT", "mert_voice")
        today = date.today().isoformat()

        for platform in ("tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4"):
            _seed_tiktok_content(tmp_db, today, platform)

        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        paths = gen.run(date.today())

        assert len(paths) == 4
        assert all(p.suffix == ".mp3" for p in paths)
        assert all(p.exists() for p in paths)

    def test_skips_existing_files(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("ELEVENLABS_VOICE_ID_MERT", "mert_voice")
        today = date.today().isoformat()
        cid = _seed_tiktok_content(tmp_db, today, "tiktok_1")

        # Dosyayı önceden oluştur
        existing = tmp_path / today / f"tiktok_1_{cid}.mp3"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"existing_audio")

        client = _mock_elevenlabs_client()
        gen = TTSGenerator(client=client)
        paths = gen.run(date.today())

        # Mevcut dosya → atlanır
        assert len(paths) == 0
        client.text_to_speech.convert.assert_not_called()

    def test_skips_compliance_failed(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("ELEVENLABS_VOICE_ID_MERT", "mert_voice")
        today = date.today().isoformat()
        db = tmp_db
        db.insert_content({
            "date": today, "platform": "tiktok_1", "title": "t", "body": "b",
            "word_count": 1, "compliance_passed": 0,
            "compliance_warnings": json.dumps([]), "prompt_version_id": None,
        })

        gen = TTSGenerator(client=_mock_elevenlabs_client())
        paths = gen.run(date.today())
        assert paths == []

    def test_api_error_skips_and_continues(self, tmp_db, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("ELEVENLABS_VOICE_ID_MERT", "mert_voice")
        today = date.today().isoformat()
        _seed_tiktok_content(tmp_db, today, "tiktok_1")
        _seed_tiktok_content(tmp_db, today, "tiktok_2")

        client = MagicMock()
        # İlk çağrıda hata, ikincisi OK
        client.text_to_speech.convert.side_effect = [
            RuntimeError("quota"),
            iter([b"audio"]),
        ]
        gen = TTSGenerator(client=client)
        paths = gen.run(date.today())

        assert len(paths) == 1  # sadece ikincisi kaydedildi

    def test_returns_empty_when_no_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        gen = TTSGenerator(client=_mock_elevenlabs_client())
        paths = gen.run(date.today())
        assert paths == []
