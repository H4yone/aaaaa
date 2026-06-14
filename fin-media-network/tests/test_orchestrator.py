"""
PipelineOrchestrator testleri — tüm bağımlılıklar mock'lanır.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from src.pipeline.orchestrator import PipelineOrchestrator, PipelineResult, StepResult


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _make_orchestrator(tmp_path: Path, **overrides) -> PipelineOrchestrator:
    cfg = {
        "pipeline": {
            "daily_run_hour": 9,
            "evening_run_hour": 17,
            "evening_run_minute": 30,
            "timezone": "Europe/Istanbul",
        }
    }
    cfg_file = tmp_path / "settings.yaml"
    cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

    defaults = dict(
        rss_fetcher=MagicMock(**{"run.return_value": [101, 102, 103]}),
        market_fetcher=MagicMock(**{"run.return_value": ["XU100.IS", "GARAN.IS"]}),
        deduplicator=MagicMock(**{"run.return_value": []}),
        clusterer=MagicMock(**{"run.return_value": [201, 202]}),
        scorer=MagicMock(**{"run.return_value": [201, 202]}),
        research_agent=MagicMock(**{"run.return_value": [1, 2]}),
        analyst_agent=MagicMock(**{"run.return_value": [3]}),
        narrative_writer=MagicMock(**{"run.return_value": [4, 5, 6]}),
        tts_generator=MagicMock(**{"run.return_value": [Path("a.mp3"), Path("b.mp3")]}),
        video_generator=MagicMock(**{"run.return_value": [Path("a.mp4")]}),
        youtube_publisher=MagicMock(**{"run.return_value": [7]}),
        x_publisher=MagicMock(**{"run.return_value": [8]}),
        tiktok_publisher=MagicMock(**{"run.return_value": [9, 10]}),
        config_path=cfg_file,
    )
    defaults.update(overrides)
    return PipelineOrchestrator(**defaults)


# ── StepResult / PipelineResult ───────────────────────────────────────────────

class TestDataclasses:
    def test_pipeline_result_success_all_ok(self):
        r = PipelineResult(run_date="2026-06-12")
        r.steps = [
            StepResult("a", True, 1),
            StepResult("b", True, 2),
        ]
        assert r.success is True

    def test_pipeline_result_success_false_on_failed_step(self):
        r = PipelineResult(run_date="2026-06-12")
        r.steps = [
            StepResult("a", True, 1),
            StepResult("b", False, 0, error="boom"),
        ]
        assert r.success is False

    def test_pipeline_result_success_false_on_budget_exceeded(self):
        r = PipelineResult(run_date="2026-06-12")
        r.steps = [StepResult("a", True, 1)]
        r.budget_exceeded = True
        assert r.success is False

    def test_pipeline_result_total_outputs(self):
        r = PipelineResult(run_date="2026-06-12")
        r.steps = [
            StepResult("a", True, 3),
            StepResult("b", True, 5),
        ]
        assert r.total_outputs == 8


# ── Normal çalışma ─────────────────────────────────────────────────────────────

class TestRunHappyPath:
    def test_returns_pipeline_result(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run(date(2026, 6, 12))
        assert isinstance(result, PipelineResult)
        assert result.run_date == "2026-06-12"

    def test_all_steps_present(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run(date(2026, 6, 12))
        names = [s.name for s in result.steps]
        for expected in (
            "rss_fetcher", "market_fetcher", "deduplicator", "clusterer", "scorer",
            "research_agent", "analyst_agent", "narrative_writer",
            "tts_generator", "video_generator",
            "youtube_publisher", "x_publisher", "tiktok_publisher",
        ):
            assert expected in names

    def test_all_steps_succeed(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run(date(2026, 6, 12))
        assert all(s.success for s in result.steps)
        assert result.success is True

    def test_output_counts_from_agents(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["rss_fetcher"].output_count == 3
        assert step_map["market_fetcher"].output_count == 2
        assert step_map["deduplicator"].output_count == 0
        assert step_map["clusterer"].output_count == 2
        assert step_map["scorer"].output_count == 2
        assert step_map["research_agent"].output_count == 2
        assert step_map["analyst_agent"].output_count == 1
        assert step_map["narrative_writer"].output_count == 3
        assert step_map["tts_generator"].output_count == 2
        assert step_map["video_generator"].output_count == 1
        assert step_map["youtube_publisher"].output_count == 1
        assert step_map["x_publisher"].output_count == 1
        assert step_map["tiktok_publisher"].output_count == 2

    def test_agents_called_with_run_date(self, tmp_path):
        run_date = date(2026, 6, 12)
        orch = _make_orchestrator(tmp_path)
        orch.run(run_date)

        orch._rss.run.assert_called_once_with(run_date)
        orch._market.run.assert_called_once_with(run_date)
        orch._dedup.run.assert_called_once_with(run_date)
        orch._clusterer.run.assert_called_once_with(run_date)
        orch._scorer.run.assert_called_once_with(run_date)
        orch._research.run.assert_called_once_with(run_date)
        orch._analyst.run.assert_called_once_with(run_date)
        orch._narrative.run.assert_called_once_with(run_date)
        orch._tts.run.assert_called_once_with(run_date)
        orch._youtube.run.assert_called_once_with(run_date)
        orch._x.run.assert_called_once_with(run_date)
        orch._tiktok.run.assert_called_once_with(run_date)

    def test_duration_recorded(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run(date(2026, 6, 12))
        assert all(s.duration_ms >= 0 for s in result.steps)

    def test_uses_today_when_no_date(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        result = orch.run()
        assert result.run_date == date.today().isoformat()


# ── Hata izolasyonu ───────────────────────────────────────────────────────────

class TestErrorIsolation:
    def test_failed_step_does_not_stop_pipeline(self, tmp_path):
        orch = _make_orchestrator(
            tmp_path,
            research_agent=MagicMock(**{"run.side_effect": RuntimeError("araştırma hatası")}),
        )
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is False
        assert step_map["research_agent"].error == "araştırma hatası"
        # Diğer adımlar yine de çalışmış olmalı
        assert step_map["analyst_agent"].success is True
        assert step_map["tts_generator"].success is True

    def test_failed_step_error_stored(self, tmp_path):
        orch = _make_orchestrator(
            tmp_path,
            tts_generator=MagicMock(**{"run.side_effect": ValueError("ses hatası")}),
        )
        result = orch.run(date(2026, 6, 12))
        step_map = {s.name: s for s in result.steps}
        assert "ses hatası" in step_map["tts_generator"].error

    def test_multiple_failed_steps_all_recorded(self, tmp_path):
        orch = _make_orchestrator(
            tmp_path,
            analyst_agent=MagicMock(**{"run.side_effect": RuntimeError("analist hatası")}),
            youtube_publisher=MagicMock(**{"run.side_effect": RuntimeError("yt hatası")}),
        )
        result = orch.run(date(2026, 6, 12))
        step_map = {s.name: s for s in result.steps}
        assert step_map["analyst_agent"].success is False
        assert step_map["youtube_publisher"].success is False
        assert step_map["research_agent"].success is True
        assert step_map["tts_generator"].success is True


# ── Bütçe aşımı ───────────────────────────────────────────────────────────────

class TestBudgetExceeded:
    def _patched(self, tmp_path, exceed_after: int = 0):
        """exceed_after: kaçıncı _budget_exceeded çağrısından sonra True döner."""
        orch = _make_orchestrator(tmp_path)
        call_count = {"n": 0}

        def fake_budget(date_str):
            call_count["n"] += 1
            return call_count["n"] > exceed_after

        orch._budget_exceeded = fake_budget
        return orch

    def test_budget_exceeded_from_start_skips_all_llm(self, tmp_path):
        orch = self._patched(tmp_path, exceed_after=0)
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is False
        assert "bütçe" in step_map["research_agent"].error
        assert step_map["analyst_agent"].success is False
        assert step_map["narrative_writer"].success is False
        assert result.budget_exceeded is True

    def test_budget_exceeded_non_llm_steps_still_run(self, tmp_path):
        orch = self._patched(tmp_path, exceed_after=0)
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["tts_generator"].success is True
        assert step_map["youtube_publisher"].success is True
        assert step_map["x_publisher"].success is True
        assert step_map["tiktok_publisher"].success is True

    def test_budget_exceeded_after_first_llm_step(self, tmp_path):
        orch = self._patched(tmp_path, exceed_after=1)
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is True
        assert step_map["analyst_agent"].success is False
        assert step_map["narrative_writer"].success is False
        assert result.budget_exceeded is True

    def test_budget_not_exceeded_all_llm_run(self, tmp_path):
        orch = self._patched(tmp_path, exceed_after=999)
        result = orch.run(date(2026, 6, 12))

        step_map = {s.name: s for s in result.steps}
        assert step_map["research_agent"].success is True
        assert step_map["analyst_agent"].success is True
        assert step_map["narrative_writer"].success is True
        assert result.budget_exceeded is False


# ── Lazy yükleme ──────────────────────────────────────────────────────────────

class TestLazyLoading:
    def test_lazy_research_loaded_once(self, tmp_path):
        cfg = {
            "pipeline": {
                "daily_run_hour": 9,
                "evening_run_hour": 17,
                "timezone": "UTC",
            }
        }
        cfg_file = tmp_path / "settings.yaml"
        cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")

        mock_agent = MagicMock(**{"run.return_value": []})
        with patch("src.intelligence.research_agent.ResearchAgent", return_value=mock_agent):
            orch = PipelineOrchestrator(config_path=cfg_file)
            agent1 = orch._get_research()
            agent2 = orch._get_research()
            assert agent1 is agent2
