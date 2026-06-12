"""
PromptOptimizer testleri — DB fixture ile tam iş mantığı doğrulanır.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src.db.database import reset_db
from src.feedback.prompt_optimizer import PromptOptimizer


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _make_version(db, platform: str, version: str, is_active: int = 1) -> int:
    return db.execute(
        """INSERT INTO prompt_versions (platform, version, prompt_text, is_active)
           VALUES (?,?,?,?)""",
        (platform, version, f"Prompt metni {version}", is_active),
    ).lastrowid


def _make_content(db, platform: str, version_id: int | None = None) -> int:
    return db.insert_content({
        "date": date.today().isoformat(),
        "platform": platform,
        "title": "Test",
        "body": "Test. Bu içerik yatırım tavsiyesi değildir.",
        "word_count": 6,
        "compliance_passed": 1,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": version_id,
    })


def _make_performance(db, content_id: int, platform: str,
                      views: int, likes: int, comments: int = 0, shares: int = 0) -> int:
    eng = (likes + comments + shares) / views if views > 0 else 0.0
    return db.execute(
        """INSERT INTO performance
           (content_id, platform, views, likes, comments, shares, engagement_rate)
           VALUES (?,?,?,?,?,?,?)""",
        (content_id, platform, views, likes, comments, shares, round(eng, 6)),
    ).lastrowid


# ── Skor hesaplama ────────────────────────────────────────────────────────────

class TestComputeScore:
    def test_basic_engagement(self):
        opt = PromptOptimizer()
        perfs = [{"views": 1000, "likes": 100, "comments": 50, "shares": 10, "engagement_rate": None}]
        score = opt._compute_score(perfs)
        assert abs(score - 0.16) < 1e-5

    def test_zero_views_uses_engagement_rate_column(self):
        opt = PromptOptimizer()
        perfs = [{"views": 0, "likes": 0, "comments": 0, "shares": 0, "engagement_rate": 0.05}]
        score = opt._compute_score(perfs)
        assert score == 0.05

    def test_empty_returns_zero(self):
        assert PromptOptimizer()._compute_score([]) == 0.0

    def test_averages_multiple(self):
        opt = PromptOptimizer()
        perfs = [
            {"views": 1000, "likes": 100, "comments": 0, "shares": 0, "engagement_rate": None},
            {"views": 1000, "likes": 200, "comments": 0, "shares": 0, "engagement_rate": None},
        ]
        score = opt._compute_score(perfs)
        assert abs(score - 0.15) < 1e-5


# ── create_version ─────────────────────────────────────────────────────────────

class TestCreateVersion:
    def test_inserts_and_returns_id(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        opt = PromptOptimizer()
        vid = opt.create_version("youtube", "v1.0", "Prompt metni")
        assert vid > 0
        row = tmp_db.fetchone("SELECT * FROM prompt_versions WHERE id=?", (vid,))
        assert row["platform"] == "youtube"
        assert row["version"] == "v1.0"
        assert row["is_active"] == 1

    def test_stores_notes_and_params(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        opt = PromptOptimizer()
        vid = opt.create_version(
            "tiktok_1", "v2.0", "Metin",
            parameter_json='{"tone":"casual"}',
            notes="A/B test versiyonu",
        )
        row = tmp_db.fetchone("SELECT * FROM prompt_versions WHERE id=?", (vid,))
        assert row["notes"] == "A/B test versiyonu"
        assert "casual" in row["parameter_json"]


# ── Tek versiyon — skor güncelleme ────────────────────────────────────────────

class TestSingleVersion:
    def test_single_version_score_updated(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        vid = _make_version(tmp_db, "youtube", "v1.0")
        cid = _make_content(tmp_db, "youtube", vid)
        _make_performance(tmp_db, cid, "youtube", 1000, 100, 50, 0)

        opt = PromptOptimizer()
        results = opt.run(date.today())

        assert results == []  # tek versiyon — A/B yapılmaz
        row = tmp_db.fetchone("SELECT performance_score FROM prompt_versions WHERE id=?", (vid,))
        assert row["performance_score"] is not None
        assert row["performance_score"] > 0

    def test_single_version_no_data_score_zero(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        vid = _make_version(tmp_db, "x_thread", "v1.0")

        opt = PromptOptimizer()
        opt.run(date.today())

        row = tmp_db.fetchone("SELECT performance_score FROM prompt_versions WHERE id=?", (vid,))
        assert row["performance_score"] == 0.0


# ── A/B test ──────────────────────────────────────────────────────────────────

class TestABTest:
    def test_winner_determined_by_engagement(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        v1 = _make_version(tmp_db, "tiktok_1", "v1.0")
        v2 = _make_version(tmp_db, "tiktok_1", "v2.0")

        # v2 daha yüksek etkileşim
        cid1 = _make_content(tmp_db, "tiktok_1", v1)
        _make_performance(tmp_db, cid1, "tiktok_1", 1000, 50)
        cid2 = _make_content(tmp_db, "tiktok_1", v2)
        _make_performance(tmp_db, cid2, "tiktok_1", 1000, 200)

        opt = PromptOptimizer()
        results = opt.run(date.today())

        assert len(results) == 1
        assert results[0]["winner_id"] == v2
        assert results[0]["loser_id"] == v1
        assert results[0]["platform"] == "tiktok_1"

    def test_loser_deactivated(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        v1 = _make_version(tmp_db, "youtube", "v1.0")
        v2 = _make_version(tmp_db, "youtube", "v2.0")

        cid1 = _make_content(tmp_db, "youtube", v1)
        _make_performance(tmp_db, cid1, "youtube", 1000, 10)
        cid2 = _make_content(tmp_db, "youtube", v2)
        _make_performance(tmp_db, cid2, "youtube", 1000, 300)

        opt = PromptOptimizer()
        opt.run(date.today())

        v1_row = tmp_db.fetchone("SELECT is_active FROM prompt_versions WHERE id=?", (v1,))
        v2_row = tmp_db.fetchone("SELECT is_active FROM prompt_versions WHERE id=?", (v2,))
        assert v1_row["is_active"] == 0  # kaybeden devre dışı
        assert v2_row["is_active"] == 1  # kazanan aktif

    def test_winner_score_stored(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        v1 = _make_version(tmp_db, "x_thread", "v1.0")
        v2 = _make_version(tmp_db, "x_thread", "v2.0")

        for vid, likes in [(v1, 50), (v2, 150)]:
            cid = _make_content(tmp_db, "x_thread", vid)
            _make_performance(tmp_db, cid, "x_thread", 1000, likes)

        opt = PromptOptimizer()
        results = opt.run(date.today())

        winner_row = tmp_db.fetchone(
            "SELECT performance_score FROM prompt_versions WHERE id=?",
            (results[0]["winner_id"],),
        )
        assert winner_row["performance_score"] == results[0]["winner_score"]

    def test_insufficient_data_no_result(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        # İki versiyon var ama hiç performance verisi yok
        _make_version(tmp_db, "youtube", "v1.0")
        _make_version(tmp_db, "youtube", "v2.0")

        opt = PromptOptimizer()
        results = opt.run(date.today())
        assert results == []

    def test_lookback_excludes_old_data(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        v1 = _make_version(tmp_db, "tiktok_2", "v1.0")
        v2 = _make_version(tmp_db, "tiktok_2", "v2.0")

        # İçerik oluştur ama eski tarihle
        old_date = (date.today() - timedelta(days=30)).isoformat()
        for vid in (v1, v2):
            cid = tmp_db.insert_content({
                "date": old_date, "platform": "tiktok_2", "title": "T",
                "body": "B", "word_count": 1, "compliance_passed": 1,
                "compliance_warnings": json.dumps([]), "prompt_version_id": vid,
            })
            _make_performance(tmp_db, cid, "tiktok_2", 1000, 100)

        opt = PromptOptimizer(lookback_days=7)  # sadece son 7 gün
        results = opt.run(date.today())
        assert results == []  # eski veri lookback dışında

    def test_empty_db_returns_empty(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        opt = PromptOptimizer()
        results = opt.run(date.today())
        assert results == []
