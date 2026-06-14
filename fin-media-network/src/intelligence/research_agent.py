"""
Research Agent — Tier 1/2 kümeleri → BIST sinyal kaydı.

Akış:
  1. Belirtilen tarih için clusters tablosundan Tier 1/2 satırları çek
  2. Her küme için transmission_matrix.yaml kurallarını anahtar kelime eşleştir
  3. LLM'e küme + eşleşen kurallar + piyasa anlık verilerini ver
  4. Gelen JSON'u ayrıştırıp signals tablosuna yaz
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.db.database import get_db
from src.intelligence.llm_client import BudgetExceeded, LLMClient

logger = logging.getLogger(__name__)

_TRANSMISSION_PATH = Path(__file__).parent.parent.parent / "config" / "transmission_matrix.yaml"
_SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

_SYSTEM_PROMPT = """\
Sen deneyimli bir Türk finansal analistisin.
Küresel finansal haberleri analiz ederek bunların BIST ve Türk ekonomisi üzerindeki etkisini değerlendiriyorsun.
Çıktın her zaman geçerli JSON olmalıdır. Türkçe yaz.\
"""

_USER_PROMPT = """\
Aşağıdaki haber kümesini analiz et ve JSON formatında sinyal üret.

## Haber Kümesi
Başlık: {representative_title}
Anahtar kelimeler: {keywords}
Kaynak ağırlığı: {source_weight:.2f}
Piyasa önemi: {market_relevance:.2f}
Volatilite etkisi: {volatility_impact:.2f}

## Eşleşen İletim Matrisi Kuralları
{matched_rules}

## Piyasa Anlık Değerleri (bugün)
{market_data}

## Görev
Aşağıdaki JSON yapısını döndür (başka hiçbir şey ekleme):
{{
  "headline": "<tek cümle Türkçe özet, max 120 karakter>",
  "what_happened": "<ne oldu — 2-3 cümle>",
  "why_it_matters": "<BIST için neden önemli — 2-3 cümle>",
  "bias": "<bullish|bearish|neutral>",
  "confidence": <0.0 ile 1.0 arası ondalık sayı>,
  "bist_impact": {{
    "overall": "<pozitif|negatif|karışık|nötr>",
    "sectors": [
      {{
        "sector": "<sektör adı>",
        "stocks": ["<TICKER.IS>"],
        "direction": "<yukarı|aşağı|nötr>",
        "reasoning": "<kısa açıklama>"
      }}
    ]
  }}
}}\
"""


class ResearchAgent:
    """Küme → sinyal dönüşümünü yönetir."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        transmission_path: Path | str | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        path = Path(transmission_path) if transmission_path else _TRANSMISSION_PATH
        self._rules: list[dict] = yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]
        settings = yaml.safe_load(_SETTINGS_PATH.read_text(encoding="utf-8"))
        self._max_clusters: int = settings.get("intelligence", {}).get("research_max_clusters", 12)

    # ── Kural eşleştirme ──────────────────────────────────────────────────────

    def _match_rules(self, keywords: list[str], title: str) -> list[dict]:
        """Küme anahtar kelimeleri + başlığına göre transmission kurallarını filtreler."""
        haystack = " ".join(keywords + [title]).lower()
        return [
            rule
            for rule in self._rules
            if any(kw.lower() in haystack for kw in rule["keywords"])
        ]

    # ── Prompt biçimlendirme ──────────────────────────────────────────────────

    @staticmethod
    def _fmt_rules(rules: list[dict]) -> str:
        if not rules:
            return "Eşleşen kural yok — genel piyasa analizi yap."
        lines = []
        for r in rules:
            lines.append(
                f"- [{r['id']}] {r['trigger']}: {r['channel']}"
                f" → BIST: {r['bist_impact']} ({r['impact_magnitude']})."
                f" Hint: {r['narrative_hint']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fmt_market(rows: list[Any]) -> str:
        if not rows:
            return "Piyasa verisi mevcut değil."
        lines = []
        for row in rows:
            chg = f"{row['change_pct']:+.2f}%" if row["change_pct"] is not None else "N/A"
            close = row["close"] if row["close"] is not None else "—"
            lines.append(f"- {row['ticker']}: {close} ({chg})")
        return "\n".join(lines)

    # ── JSON ayrıştırma ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Markdown kod bloğu içinde ya da düz gelen JSON'u ayrıştırır."""
        # ```json ... ``` veya ``` ... ``` bloğunu ayıkla
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        # İlk { ile son } arasını al
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise json.JSONDecodeError("JSON bulunamadı", raw, 0)

    # ── Ana çalışma döngüsü ───────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Belirtilen tarih için Tier 1/2 kümelerini analiz eder.

        Returns:
            Eklenen signal satırlarının ID listesi.
        """
        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        clusters = db.fetchall(
            "SELECT * FROM clusters WHERE date=? AND tier IN (1,2) ORDER BY score DESC LIMIT ?",
            (date_str, self._max_clusters),
        )
        if not clusters:
            logger.info("[ResearchAgent] %s tarihinde işlenecek Tier 1/2 küme yok", date_str)
            return []

        market_rows = db.fetchall(
            "SELECT ticker, close, change_pct FROM market_snapshots WHERE date=?",
            (date_str,),
        )

        signal_ids: list[int] = []

        for rank, cluster in enumerate(clusters, start=1):
            keywords: list[str] = json.loads(cluster["keywords"] or "[]")
            matched = self._match_rules(keywords, cluster["representative_title"])
            rule_ids = [r["id"] for r in matched]

            prompt = _USER_PROMPT.format(
                representative_title=cluster["representative_title"],
                keywords=", ".join(keywords) if keywords else "—",
                source_weight=cluster["source_weight"],
                market_relevance=cluster["market_relevance"],
                volatility_impact=cluster["volatility_impact"],
                matched_rules=self._fmt_rules(matched),
                market_data=self._fmt_market(list(market_rows)),
            )

            try:
                resp = self._llm.call(
                    agent="research",
                    messages=[{"role": "user", "content": prompt}],
                    system=_SYSTEM_PROMPT,
                )
                parsed = self._parse_json(resp.content)

            except BudgetExceeded:
                logger.warning(
                    "[ResearchAgent] Token bütçesi aşıldı — %d küme işlenemedi",
                    len(clusters) - rank + 1,
                )
                break

            except json.JSONDecodeError as exc:
                logger.error(
                    "[ResearchAgent] Küme %d: LLM yanıtı JSON değil: %s",
                    cluster["id"],
                    exc,
                )
                continue

            except Exception as exc:
                logger.error(
                    "[ResearchAgent] Küme %d: LLM çağrısı başarısız: %s",
                    cluster["id"],
                    exc,
                )
                continue

            signal_id = db.insert_signal({
                "date": date_str,
                "cluster_id": cluster["id"],
                "headline": parsed.get("headline", ""),
                "what_happened": parsed.get("what_happened", ""),
                "why_it_matters": parsed.get("why_it_matters", ""),
                "bias": parsed.get("bias", "neutral"),
                "confidence": parsed.get("confidence", 0.5),
                "transmission_rule_ids": json.dumps(rule_ids),
                "bist_impact_json": json.dumps(parsed.get("bist_impact", {})),
                "rank": rank,
            })
            signal_ids.append(signal_id)
            logger.info(
                "[ResearchAgent] Sinyal #%d eklendi (küme=%d, rank=%d, bias=%s, conf=%.2f)",
                signal_id,
                cluster["id"],
                rank,
                parsed.get("bias", "?"),
                parsed.get("confidence", 0.0),
            )

        return signal_ids
