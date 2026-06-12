"""
End-to-end entegrasyon testleri.

Gerçek SQLite DB, tüm dış API'ler (LLM / ElevenLabs / YouTube / X / TikTok) mock.
Pipeline'ın uçtan uca akışını doğrular.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.db.database import reset_db
from src.pipeline.orchestrator import PipelineOrchestrator


# ── Fixture'lar ───────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "e2e.db")
    db.init()
    return db


@pytest.fixture()
def cfg_file(tmp_path):
    cfg = {
        "pipeline": {
            "daily_run_hour": 6,
            "evening_run_hour": 18,
            "timezone": "UTC",
        }
    }
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


def _make_orch(cfg_file: Path, **overrides) -> PipelineOrchestrator:
    defaults = {
        "rss_fetcher":      MagicMock(**{"run.return_value": [1, 2, 3]}),
        "market_fetcher":   MagicMock(**{"run.return_value": ["XU100.IS"]}),
        "deduplicator":     MagicMock(**{"run.return_value": []}),
        "clusterer":        MagicMock(**{"run.return_value": [10, 11]}),
        "scorer":           MagicMock(**{"run.return_value": [10, 11]}),
        "research_agent":   MagicMock(**{"run.return_value": [1, 2]}),
        "analyst_agent":    MagicMock(**{"run.return_value": [3]}),
        "narrative_writer": MagicMock(**{"run.return_value": [4, 5, 6, 7, 8]}),
        "tts_generator":    MagicMock(**{"run.return_value": [Path("a.mp3")]}),
        "youtube_publisher":MagicMock(**{"run.return_value": [4]}),
        "x_publisher":      MagicMock(**{"run.return_value": [8]}),
        "tiktok_publisher": MagicMock(**{"run.return_value": [5, 6, 7]}),
        "config_path":      cfg_file,
    }
    defaults.update(overrides)
    return PipelineOrchestrator(**defaults)


# ── Temel akış ────────────────────────────────────────────────────────────────

class TestFullPipelineFlow:
    def test_run_returns_pipeline_result(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        result = orch.run(date.today())

        assert result.run_date == date.today().isoformat()
        assert len(result.steps) == 12

    def test_all_agents_called_once(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        orch.run(date.today())

        orch._rss.run.assert_called_once_with(date.today())
        orch._market.run.assert_called_once_with(date.today())
        orch._research.run.assert_called_once_with(date.today())
        orch._analyst.run.assert_called_once_with(date.today())
        orch._narrative.run.assert_called_once_with(date.today())
        orch._tts.run.assert_called_once_with(date.today())
        orch._youtube.run.assert_called_once_with(date.today())
        orch._x.run.assert_called_once_with(date.today())
        orch._tiktok.run.assert_called_once_with(date.today())

    def test_total_outputs_summed(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        result = orch.run(date.today())
        # rss=3, market=1, dedup=0, cluster=2, scorer=2, research=2, analyst=1,
        # narrative=5, tts=1, youtube=1, x=1, tiktok=3
        assert result.total_outputs == 22

    def test_step_names_in_order(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        result = orch.run(date.today())
        names = [s.name for s in result.steps]
        assert names == [
            "rss_fetcher", "market_fetcher", "deduplicator", "clusterer", "scorer",
            "research_agent", "analyst_agent", "narrative_writer",
            "tts_generator", "youtube_publisher", "x_publisher", "tiktok_publisher",
        ]


# ── Hata yalıtımı ─────────────────────────────────────────────────────────────

class TestPipelineErrorIsolation:
    def test_research_failure_does_not_block_others(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(
            cfg_file,
            research_agent=MagicMock(**{"run.side_effect": RuntimeError("api down")}),
        )
        result = orch.run(date.today())

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is False
        assert step_map["analyst_agent"].success is True
        assert step_map["tts_generator"].success is True
        assert step_map["tiktok_publisher"].success is True

    def test_tts_failure_does_not_block_publishers(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(
            cfg_file,
            tts_generator=MagicMock(**{"run.side_effect": RuntimeError("quota")}),
        )
        result = orch.run(date.today())

        step_map = {s.name: s for s in result.steps}
        assert step_map["tts_generator"].success is False
        assert step_map["youtube_publisher"].success is True
        assert step_map["x_publisher"].success is True

    def test_pipeline_result_success_false_when_any_step_fails(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(
            cfg_file,
            x_publisher=MagicMock(**{"run.side_effect": RuntimeError("oauth")}),
        )
        result = orch.run(date.today())
        assert result.success is False


# ── Bütçe aşımı ───────────────────────────────────────────────────────────────

class TestBudgetExceededFlow:
    def test_llm_steps_skipped_non_llm_run(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        # Bütçe her zaman aşılmış gibi görünsün
        orch._budget_exceeded = lambda _: True
        result = orch.run(date.today())

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is False
        assert step_map["analyst_agent"].success is False
        assert step_map["narrative_writer"].success is False
        assert step_map["tts_generator"].success is True
        assert step_map["youtube_publisher"].success is True
        assert result.budget_exceeded is True

    def test_llm_agents_not_called_on_budget_exceeded(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        orch = _make_orch(cfg_file)
        orch._budget_exceeded = lambda _: True
        orch.run(date.today())

        orch._research.run.assert_not_called()
        orch._analyst.run.assert_not_called()
        orch._narrative.run.assert_not_called()
        orch._tts.run.assert_called_once()
        orch._tiktok.run.assert_called_once()


# ── DB entegrasyonu ───────────────────────────────────────────────────────────

class TestDBIntegration:
    def _seed_full_content(self, db, date_str: str) -> dict[str, int]:
        """Gerçekçi içerik satırları ekler, ID haritası döner."""
        ids: dict[str, int] = {}
        for platform in ("youtube", "tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4", "x_thread"):
            body = '{"tweets":["BIST düştü. Bu içerik yatırım tavsiyesi değildir."]}' \
                   if platform == "x_thread" else \
                   "BIST analizi. Bu içerik yatırım tavsiyesi değildir."
            cid = db.insert_content({
                "date": date_str,
                "platform": platform,
                "title": f"{platform} başlık",
                "body": body,
                "word_count": 8,
                "compliance_passed": 1,
                "compliance_warnings": json.dumps([]),
                "prompt_version_id": None,
            })
            ids[platform] = cid
        return ids

    def test_published_content_recorded(self, tmp_db, cfg_file, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
        today = date.today().isoformat()
        ids = self._seed_full_content(tmp_db, today)

        # Publisher'ları gerçekten çalıştır (DB güncelleyen mock'lar)
        def fake_yt_run(d):
            cid = ids["youtube"]
            tmp_db.execute(
                "UPDATE content SET published_at='2026-06-12 10:00:00', "
                "publish_url='https://youtube.com/watch?v=abc123' WHERE id=?",
                (cid,),
            )
            return [cid]

        orch = _make_orch(
            cfg_file,
            youtube_publisher=MagicMock(**{"run.side_effect": fake_yt_run}),
        )
        orch.run(date.today())

        row = tmp_db.fetchone(
            "SELECT published_at, publish_url FROM content WHERE id=?",
            (ids["youtube"],),
        )
        assert row["published_at"] is not None
        assert "abc123" in row["publish_url"]

    def test_performance_metrics_stored(self, tmp_db, cfg_file, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        ids = self._seed_full_content(tmp_db, today)
        yt_cid = ids["youtube"]

        tmp_db.execute(
            "UPDATE content SET published_at='2026-06-12 10:00:00', "
            "publish_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ' WHERE id=?",
            (yt_cid,),
        )

        from src.feedback.metrics_fetcher import MetricsFetcher
        yt_svc = MagicMock()
        yt_svc.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"statistics": {"viewCount": "5000", "likeCount": "250", "commentCount": "30"}}]
        }
        fetcher = MetricsFetcher(youtube_service=yt_svc)
        perf_ids = fetcher.run(date.today())

        assert len(perf_ids) == 1
        perf = tmp_db.fetchone("SELECT views, likes FROM performance WHERE id=?", (perf_ids[0],))
        assert perf["views"] == 5000
        assert perf["likes"] == 250

    def test_ab_test_updates_prompt_versions(self, tmp_db, cfg_file, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()

        v1 = tmp_db.execute(
            "INSERT INTO prompt_versions (platform, version, prompt_text, is_active) VALUES (?,?,?,1)",
            ("youtube", "v1.0", "Prompt A"),
        ).lastrowid
        v2 = tmp_db.execute(
            "INSERT INTO prompt_versions (platform, version, prompt_text, is_active) VALUES (?,?,?,1)",
            ("youtube", "v2.0", "Prompt B"),
        ).lastrowid

        for vid, likes in [(v1, 30), (v2, 150)]:
            cid = tmp_db.insert_content({
                "date": today, "platform": "youtube", "title": "t",
                "body": "b", "word_count": 1, "compliance_passed": 1,
                "compliance_warnings": "[]", "prompt_version_id": vid,
            })
            tmp_db.execute(
                "INSERT INTO performance (content_id, platform, views, likes, engagement_rate) "
                "VALUES (?,?,?,?,?)",
                (cid, "youtube", 1000, likes, likes / 1000),
            )

        from src.feedback.prompt_optimizer import PromptOptimizer
        results = PromptOptimizer().run(date.today())

        assert results[0]["winner_id"] == v2
        loser = tmp_db.fetchone("SELECT is_active FROM prompt_versions WHERE id=?", (v1,))
        assert loser["is_active"] == 0


# ── CLI smoke testleri ────────────────────────────────────────────────────────

class TestCLI:
    def test_run_command_exits_zero(self, tmp_db, cfg_file, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

        from src.cli import main
        with patch("src.pipeline.orchestrator.PipelineOrchestrator") as MockOrch:
            mock_result = MagicMock()
            mock_result.run_date = date.today().isoformat()
            mock_result.success = True
            mock_result.total_outputs = 5
            mock_result.budget_exceeded = False
            mock_result.steps = []
            MockOrch.return_value.run.return_value = mock_result

            exit_code = main(["run"])
        assert exit_code == 0

    def test_run_with_date_flag(self, tmp_db, cfg_file, monkeypatch, tmp_path):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))

        from src.cli import main
        with patch("src.pipeline.orchestrator.PipelineOrchestrator") as MockOrch:
            mock_result = MagicMock()
            mock_result.run_date = "2026-06-01"
            mock_result.success = True
            mock_result.total_outputs = 0
            mock_result.budget_exceeded = False
            mock_result.steps = []
            MockOrch.return_value.run.return_value = mock_result

            exit_code = main(["run", "--date", "2026-06-01"])
        assert exit_code == 0

    def test_run_invalid_date_exits_one(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        from src.cli import main
        exit_code = main(["run", "--date", "not-a-date"])
        assert exit_code == 1

    def test_status_command_exits_zero(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        from src.cli import main
        exit_code = main(["status"])
        assert exit_code == 0

    def test_init_db_command(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "new.db"))
        from src.cli import main
        exit_code = main(["init-db"])
        assert exit_code == 0
        assert (tmp_path / "new.db").exists()
