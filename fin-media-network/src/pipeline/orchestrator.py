"""
Pipeline Orchestrator — tüm katmanları sırayla koordine eder.

Akış:
  ResearchAgent → AnalystAgent → NarrativeWriter
      → TTSGenerator → YouTubePublisher + XPublisher + TikTokPublisher

Kurallar:
  - LLM adımları sıralı; biri başarısız olursa loglanır, sonraki devam eder
  - LLM bütçesi aşılınca kalan LLM adımları atlanır (non-LLM adımlar devam)
  - Her adımın süresi ve çıktı sayısı PipelineResult'a yazılır
  - Zamanlama settings.yaml → pipeline.daily_run_hour / evening_run_hour
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"


# ── Veri yapıları ─────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    success: bool
    output_count: int
    error: str | None = None
    duration_ms: int = 0


@dataclass
class PipelineResult:
    run_date: str
    steps: list[StepResult] = field(default_factory=list)
    budget_exceeded: bool = False

    @property
    def success(self) -> bool:
        return all(s.success for s in self.steps) and not self.budget_exceeded

    @property
    def total_outputs(self) -> int:
        return sum(s.output_count for s in self.steps)


# ── Orchestrator ──────────────────────────────────────────────────────────────

class PipelineOrchestrator:
    """
    Tüm pipeline adımlarını sırayla çalıştırır.

    Her bağımlılık dışarıdan enjekte edilir → testlerde mock kolaylaşır.
    Prodüksiyonda None bırakıldığında her modül kendi default'unu kullanır.
    """

    def __init__(
        self,
        research_agent=None,
        analyst_agent=None,
        narrative_writer=None,
        tts_generator=None,
        youtube_publisher=None,
        x_publisher=None,
        tiktok_publisher=None,
        config_path: str | Path | None = None,
    ) -> None:
        self._research = research_agent
        self._analyst = analyst_agent
        self._narrative = narrative_writer
        self._tts = tts_generator
        self._youtube = youtube_publisher
        self._x = x_publisher
        self._tiktok = tiktok_publisher

        cfg_path = Path(config_path) if config_path else _CONFIG_PATH
        pipeline_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["pipeline"]
        self._daily_hour: int = pipeline_cfg["daily_run_hour"]
        self._evening_hour: int = pipeline_cfg["evening_run_hour"]
        self._evening_minute: int = pipeline_cfg.get("evening_run_minute", 0)
        self._tz_name: str = pipeline_cfg["timezone"]

    # ── Lazy agent yükleme ────────────────────────────────────────────────────

    def _get_research(self):
        if self._research is None:
            from src.intelligence.research_agent import ResearchAgent
            self._research = ResearchAgent()
        return self._research

    def _get_analyst(self):
        if self._analyst is None:
            from src.intelligence.analyst_agent import AnalystAgent
            self._analyst = AnalystAgent()
        return self._analyst

    def _get_narrative(self):
        if self._narrative is None:
            from src.content.narrative_writer import NarrativeWriter
            self._narrative = NarrativeWriter()
        return self._narrative

    def _get_tts(self):
        if self._tts is None:
            from src.production.tts_generator import TTSGenerator
            self._tts = TTSGenerator()
        return self._tts

    def _get_youtube(self):
        if self._youtube is None:
            from src.production.youtube_publisher import YouTubePublisher
            self._youtube = YouTubePublisher()
        return self._youtube

    def _get_x(self):
        if self._x is None:
            from src.production.x_publisher import XPublisher
            self._x = XPublisher()
        return self._x

    def _get_tiktok(self):
        if self._tiktok is None:
            from src.production.tiktok_publisher import TikTokPublisher
            self._tiktok = TikTokPublisher()
        return self._tiktok

    # ── Bütçe kontrolü ───────────────────────────────────────────────────────

    def _budget_exceeded(self, date_str: str) -> bool:
        from src.intelligence.llm_client import LLMClient, BudgetExceeded
        try:
            LLMClient()._check_budget()
            return False
        except BudgetExceeded:
            return True

    # ── Adım çalıştırma ───────────────────────────────────────────────────────

    def _run_step(self, name: str, fn: Callable) -> StepResult:
        start = time.monotonic()
        try:
            output = fn()
            count = len(output) if hasattr(output, "__len__") else int(bool(output))
            duration = int((time.monotonic() - start) * 1000)
            logger.info("[Pipeline] %-20s ✓ çıktı=%d  %dms", name, count, duration)
            return StepResult(name=name, success=True,
                              output_count=count, duration_ms=duration)
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.error("[Pipeline] %-20s ✗ %s", name, exc)
            return StepResult(name=name, success=False, output_count=0,
                              error=str(exc), duration_ms=duration)

    # ── Ana çalıştırma ────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> PipelineResult:
        """
        Tüm pipeline adımlarını belirtilen tarih için çalıştırır.

        LLM bütçesi aşılınca kalan LLM adımları atlanır;
        TTS ve publisher adımları önceden üretilen içeriklerle devam eder.
        """
        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()

        result = PipelineResult(run_date=date_str)
        logger.info("[Pipeline] === %s başlıyor ===", date_str)

        # ── LLM adımları ─────────────────────────────────────────────────────
        llm_steps: list[tuple[str, Callable]] = [
            ("research_agent",   lambda: self._get_research().run(run_date)),
            ("analyst_agent",    lambda: self._get_analyst().run(run_date)),
            ("narrative_writer", lambda: self._get_narrative().run(run_date)),
        ]

        for name, fn in llm_steps:
            if self._budget_exceeded(date_str):
                result.budget_exceeded = True
                result.steps.append(StepResult(
                    name=name, success=False, output_count=0,
                    error="Token bütçesi aşıldı — adım atlandı",
                ))
                logger.warning("[Pipeline] %s atlandı: bütçe aşıldı", name)
            else:
                result.steps.append(self._run_step(name, fn))

        # ── Non-LLM adımlar (her zaman çalışır) ──────────────────────────────
        non_llm_steps: list[tuple[str, Callable]] = [
            ("tts_generator",      lambda: self._get_tts().run(run_date)),
            ("youtube_publisher",  lambda: self._get_youtube().run(run_date)),
            ("x_publisher",        lambda: self._get_x().run(run_date)),
            ("tiktok_publisher",   lambda: self._get_tiktok().run(run_date)),
        ]

        for name, fn in non_llm_steps:
            result.steps.append(self._run_step(name, fn))

        logger.info(
            "[Pipeline] === %s tamamlandı — başarı=%s bütçe_aşıldı=%s toplam_çıktı=%d ===",
            date_str, result.success, result.budget_exceeded, result.total_outputs,
        )
        return result

    # ── Zamanlama ─────────────────────────────────────────────────────────────

    def run_scheduled(self) -> None:
        """
        settings.yaml'daki saatlerde pipeline'ı otomatik çalıştırır.
        Ctrl+C ile durdurulabilir.
        """
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(self._tz_name)
        except Exception:
            import datetime as _dt
            tz = _dt.timezone.utc

        run_hours = {
            (self._daily_hour, 0),
            (self._evening_hour, self._evening_minute),
        }

        logger.info(
            "[Pipeline] Zamanlayıcı başladı — çalışma saatleri: %s (%s)",
            run_hours,
            self._tz_name,
        )

        last_run_key: str | None = None

        while True:
            now = datetime.now(tz)
            run_key = f"{now.date().isoformat()}_{now.hour:02d}:{now.minute:02d}"

            for hour, minute in run_hours:
                if now.hour == hour and now.minute == minute and run_key != last_run_key:
                    last_run_key = run_key
                    self.run(now.date())
                    break

            time.sleep(30)  # 30 saniyede bir saat kontrolü
