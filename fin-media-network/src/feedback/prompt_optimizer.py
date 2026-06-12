"""
Prompt Optimizer — A/B test ile en iyi prompt versiyonunu seçer.

Akış:
  1. performance tablosundan son N gündeki veriler çekilir
  2. Her prompt_version_id için engagement_rate ortalaması hesaplanır
  3. Aynı platform için birden fazla aktif versiyon varsa kazanan belirlenir
  4. Kazananın performance_score'u güncellenir; kaybedenin is_active → 0
  5. Sonuçlar dict olarak döner

Env: —  (tüm veriler DB'den okunur)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = 7
_MIN_SAMPLES = 1  # karşılaştırma için gereken minimum veri noktası


class PromptOptimizer:
    """
    A/B test mantığıyla prompt versiyonlarını değerlendirir.

    Testlerde `llm_client` enjekte edilebilir (gelecekte LLM-guided öneri için).
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self._llm = llm_client
        self._lookback_days = lookback_days

    # ── Skor hesaplama ────────────────────────────────────────────────────────

    def _compute_score(self, performances: list[dict]) -> float:
        """Engagement rate ortalamasını döner. Veri yoksa 0.0."""
        if not performances:
            return 0.0
        rates: list[float] = []
        for p in performances:
            views = p.get("views") or 0
            if views > 0:
                eng = (
                    (p.get("likes") or 0)
                    + (p.get("comments") or 0)
                    + (p.get("shares") or 0)
                ) / views
            else:
                eng = p.get("engagement_rate") or 0.0
            rates.append(eng)
        return round(sum(rates) / len(rates), 6)

    # ── A/B test ──────────────────────────────────────────────────────────────

    def _run_ab_test(
        self, db, platform: str, version_ids: list[int]
    ) -> dict | None:
        """
        Aynı platform için birden fazla aktif versiyon varsa kazananı seçer.

        Returns:
            {"winner_id": int, "loser_id": int, "platform": str,
             "winner_score": float, "loser_score": float}
            veya None (yeterli veri yoksa).
        """
        cutoff = (date.today() - timedelta(days=self._lookback_days)).isoformat()

        version_perfs: dict[int, list[dict]] = defaultdict(list)
        for vid in version_ids:
            rows = db.fetchall(
                """SELECT p.views, p.likes, p.comments, p.shares, p.engagement_rate
                   FROM performance p
                   JOIN content c ON c.id = p.content_id
                   WHERE c.prompt_version_id = ?
                     AND c.date >= ?""",
                (vid, cutoff),
            )
            version_perfs[vid] = [dict(r) for r in rows]

        # Yeterli veri yoksa atlama
        viable = {
            vid: perfs
            for vid, perfs in version_perfs.items()
            if len(perfs) >= _MIN_SAMPLES
        }
        if len(viable) < 2:
            logger.info(
                "[PromptOptimizer] %s platformu için yeterli A/B verisi yok", platform
            )
            return None

        scores = {vid: self._compute_score(perfs) for vid, perfs in viable.items()}
        winner_id = max(scores, key=lambda v: scores[v])
        loser_id = min(scores, key=lambda v: scores[v])

        if winner_id == loser_id:
            return None

        return {
            "winner_id": winner_id,
            "loser_id": loser_id,
            "platform": platform,
            "winner_score": scores[winner_id],
            "loser_score": scores[loser_id],
        }

    # ── Ana çalışma ───────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[dict]:
        """
        Tüm platformlar için A/B testi çalıştırır.

        Returns:
            Her platform için {"winner_id", "loser_id", "platform",
            "winner_score", "loser_score"} listesi.
            Karşılaştırma yapılamayan platformlar atlanır.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()

        db = get_db()

        # Aktif prompt versiyonlarını platform bazında grupla
        rows = db.fetchall(
            "SELECT id, platform, version FROM prompt_versions WHERE is_active=1",
        )

        platform_versions: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            platform_versions[row["platform"]].append(row["id"])

        results: list[dict] = []

        for platform, version_ids in platform_versions.items():
            if len(version_ids) < 2:
                # Tek versiyon — sadece skoru hesapla ve güncelle
                vid = version_ids[0]
                cutoff = (
                    date.today() - timedelta(days=self._lookback_days)
                ).isoformat()
                perfs = db.fetchall(
                    """SELECT p.views, p.likes, p.comments, p.shares, p.engagement_rate
                       FROM performance p
                       JOIN content c ON c.id = p.content_id
                       WHERE c.prompt_version_id = ?
                         AND c.date >= ?""",
                    (vid, cutoff),
                )
                score = self._compute_score([dict(r) for r in perfs])
                db.execute(
                    "UPDATE prompt_versions SET performance_score=? WHERE id=?",
                    (score, vid),
                )
                logger.info(
                    "[PromptOptimizer] %s v%s tek aktif — skor=%.4f",
                    platform, vid, score,
                )
                continue

            result = self._run_ab_test(db, platform, version_ids)
            if result is None:
                continue

            winner_id = result["winner_id"]
            loser_id = result["loser_id"]

            # Skorları kaydet
            db.execute(
                "UPDATE prompt_versions SET performance_score=? WHERE id=?",
                (result["winner_score"], winner_id),
            )
            db.execute(
                "UPDATE prompt_versions SET performance_score=? WHERE id=?",
                (result["loser_score"], loser_id),
            )
            # Kaybedeni devre dışı bırak
            db.execute(
                "UPDATE prompt_versions SET is_active=0 WHERE id=?",
                (loser_id,),
            )

            logger.info(
                "[PromptOptimizer] %s A/B sonuç → kazanan=%d (%.4f) kaybeden=%d (%.4f)",
                platform, winner_id, result["winner_score"],
                loser_id, result["loser_score"],
            )
            results.append(result)

        return results

    # ── Yeni versiyon oluşturma ───────────────────────────────────────────────

    def create_version(
        self,
        platform: str,
        version: str,
        prompt_text: str,
        parameter_json: str | None = None,
        notes: str | None = None,
    ) -> int:
        """
        Yeni bir prompt versiyonu oluşturur ve DB'ye yazar.

        Returns:
            Yeni satırın ID'si.
        """
        from src.db.database import get_db
        db = get_db()
        row_id = db.execute(
            """INSERT INTO prompt_versions
               (platform, version, prompt_text, parameter_json, is_active, notes)
               VALUES (?,?,?,?,1,?)""",
            (platform, version, prompt_text, parameter_json, notes),
        ).lastrowid
        logger.info("[PromptOptimizer] Yeni prompt versiyonu: %s %s (id=%d)", platform, version, row_id)
        return row_id
