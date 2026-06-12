"""
SPK Uyum Denetçisi — içeriği yayına girmeden önce tarar.

Kurallar (config/banned_phrases.yaml):
  banned_patterns  → eşleşme varsa passed=False, içerik yayınlanamaz
  warning_patterns → eşleşme varsa uyarı eklenir, içerik geçer
  required_endings → hiçbiri yoksa mandatory_disclaimer otomatik eklenir
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "banned_phrases.yaml"


@dataclass
class ComplianceResult:
    passed: bool
    warnings: list[str]
    body: str  # disclaimer eklenmişse güncellenmiş metin


class ComplianceChecker:
    """
    İçerik metnini SPK yasak kalıplarına göre denetler.

    Kullanım:
        checker = ComplianceChecker()
        result = checker.check(body_text)
        if result.passed:
            db.insert_content({..., "body": result.body, ...})
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        path = Path(config_path) if config_path else _CONFIG_PATH
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))

        self._disclaimer: str = cfg["mandatory_disclaimer"]
        self._banned: list[dict] = cfg.get("banned_patterns", [])
        self._warnings: list[dict] = cfg.get("warning_patterns", [])
        self._required_endings: list[str] = cfg.get("required_endings", [])

    # ── Yardımcılar ───────────────────────────────────────────────────────────

    @staticmethod
    def _compile(pattern: str, context_required: bool) -> re.Pattern:
        """
        context_required=True olanlar için kelime sınırı (\b) ekler.
        Türkçe özel karakterler de kapsansın diye re.UNICODE kullanılır.
        """
        if context_required:
            pattern = rf"\b{re.escape(pattern)}\b"
        return re.compile(pattern, re.IGNORECASE | re.UNICODE)

    # ── Ana denetim ───────────────────────────────────────────────────────────

    def check(self, body: str) -> ComplianceResult:
        """
        İçeriği tarar.

        Returns:
            ComplianceResult(passed, warnings, body)
            body: gerekirse zorunlu disclaimer eklenmiş metin
        """
        violations: list[str] = []
        warnings: list[str] = []

        # 1. Yasak kalıplar
        for entry in self._banned:
            ctx = bool(entry.get("context_required", False))
            rx = self._compile(entry["pattern"], ctx)
            if rx.search(body):
                msg = f"YASAK: «{entry['pattern']}» — {entry['reason']}"
                violations.append(msg)
                logger.warning("[Compliance] %s", msg)

        if violations:
            return ComplianceResult(passed=False, warnings=violations, body=body)

        # 2. Uyarı kalıpları
        for entry in self._warnings:
            rx = self._compile(entry["pattern"], context_required=False)
            if rx.search(body):
                msg = f"UYARI: «{entry['pattern']}» — {entry['reason']}"
                warnings.append(msg)
                logger.info("[Compliance] %s", msg)

        # 3. Zorunlu kapanış kontrolü
        lower = body.lower()
        has_ending = any(ending.lower() in lower for ending in self._required_endings)
        if not has_ending:
            body = body.rstrip() + "\n\n" + self._disclaimer
            logger.info("[Compliance] Zorunlu disclaimer eklendi.")

        return ComplianceResult(passed=True, warnings=warnings, body=body)
