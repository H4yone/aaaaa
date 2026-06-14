"""
Analyst Agent — her sinyal için BIST'e özgü senaryo analizi.

research_agent → signals tablosuna genel sinyal yazar.
analyst_agent  → o sinyali alır, tetikleyici koşulları sayısal olarak
                 doğrular, bull/base/bear senaryo analizi üretir ve
                 content tablosuna "analyst_brief" platformuyla yazar.

Akış:
  1. Belirtilen tarih için signals tablosunu çek
  2. Her sinyalin transmission_rule_ids'ini al → kuralları yükle
  3. Kuralların trigger_condition'larını market_snapshots ile karşılaştır
  4. LLM'e sinyal + koşul sonuçları + piyasa verisi → senaryo JSON
  5. content tablosuna platform="analyst_brief" olarak yaz
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

# Trigger koşul anahtarı → market_snapshots'taki ticker
_CONDITION_TICKER: dict[str, str] = {
    "dgs10_change_pct":      "^TNX",
    "fedfunds_change_pct":   "FEDFUNDS",
    "ndx_change_pct":        "^NDX",
    "vix_level":             "^VIX",
    "cl_change_pct":         "CL=F",
    "dxy_change_pct":        "DX-Y.NYB",
    "usdtry_change_pct":     "USDTRY=X",
    "tcmb_rate_change_bps":  "TP.TG2.Y01",
    "btc_change_pct":        "bitcoin",
}

_SYSTEM_PROMPT = """\
Sen kıdemli bir BIST stratejistisin.
Sana bir haber sinyali, tetikleyici koşulların gerçekleşip gerçekleşmediği
ve piyasa anlık verileri verilecek.
Görüşlerini Türkçe, yapılandırılmış JSON olarak sun.
Kesin fiyat tahmini verme; senaryoları olasılıklarla ifade et.\
"""

_USER_PROMPT = """\
## Sinyal
Başlık      : {headline}
Ne oldu     : {what_happened}
Neden önemli: {why_it_matters}
Genel yön   : {bias} (güven: {confidence:.0%})

## Research Agent'ın İlk BIST Değerlendirmesi
{initial_impact}

## Tetikleyici Koşul Kontrolü
{trigger_checks}

## Güncel Piyasa Verileri
{market_data}

## Görev
Aşağıdaki JSON yapısını döndür (başka hiçbir şey ekleme):
{{
  "scenarios": {{
    "bull": {{
      "probability": <0.0-1.0>,
      "description": "<2-3 cümle — iyimser senaryo>",
      "stocks": [
        {{"ticker": "<TICKER.IS>", "direction": "<yukarı|nötr>", "reasoning": "<kısa>"}}
      ]
    }},
    "base": {{
      "probability": <0.0-1.0>,
      "description": "<2-3 cümle — baz senaryo>",
      "stocks": [
        {{"ticker": "<TICKER.IS>", "direction": "<yukarı|aşağı|nötr>", "reasoning": "<kısa>"}}
      ]
    }},
    "bear": {{
      "probability": <0.0-1.0>,
      "description": "<2-3 cümle — kötümser senaryo>",
      "stocks": [
        {{"ticker": "<TICKER.IS>", "direction": "<aşağı|nötr>", "reasoning": "<kısa>"}}
      ]
    }}
  }},
  "time_horizon": "<ayni_gun|hafta|ay>",
  "trigger_conditions_active": <true|false>,
  "key_risk": "<tek cümle — en kritik aşağı risk>",
  "key_opportunity": "<tek cümle — en kritik yukarı fırsat>"
}}\
"""


class AnalystAgent:
    """Sinyal → analyst_brief dönüşümünü yönetir."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        transmission_path: Path | str | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        path = Path(transmission_path) if transmission_path else _TRANSMISSION_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]
        self._rules: dict[str, dict] = {r["id"]: r for r in raw}
        settings = yaml.safe_load(_SETTINGS_PATH.read_text(encoding="utf-8"))
        self._max_signals: int = settings.get("intelligence", {}).get("analyst_max_signals", 6)

    # ── Trigger koşul değerlendirme ───────────────────────────────────────────

    def _evaluate_conditions(
        self,
        rule: dict,
        market_by_ticker: dict[str, Any],
    ) -> list[dict]:
        """
        Kuralın trigger_condition sözlüğündeki her koşulu piyasa verisiyle karşılaştırır.

        Returns:
            [{"condition_key": ..., "operator": ..., "threshold": ...,
              "actual": ..., "met": bool}]
        """
        results = []
        for key, expr in rule.get("trigger_condition", {}).items():
            ticker = _CONDITION_TICKER.get(key)
            actual: float | None = None

            if ticker and ticker in market_by_ticker:
                row = market_by_ticker[ticker]
                # vix_level → close, diğerleri → change_pct
                actual = row["close"] if key == "vix_level" else row["change_pct"]

            # expr: ">0.05" | "<-0.10" | ">2.0" vb.
            m = re.match(r"([<>]=?)\s*(-?[\d.]+)", str(expr))
            if not m:
                results.append({"condition_key": key, "operator": "?", "threshold": expr,
                                 "actual": actual, "met": False})
                continue

            op, thr = m.group(1), float(m.group(2))
            met = False
            if actual is not None:
                met = (
                    (op == ">"  and actual > thr) or
                    (op == ">=" and actual >= thr) or
                    (op == "<"  and actual < thr)  or
                    (op == "<=" and actual <= thr)
                )

            results.append({
                "condition_key": key,
                "operator": op,
                "threshold": thr,
                "actual": actual,
                "met": met,
            })

        return results

    @staticmethod
    def _fmt_trigger_checks(checks_by_rule: dict[str, list[dict]]) -> str:
        if not checks_by_rule:
            return "Tetikleyici koşul tanımlı değil."
        lines = []
        for rule_id, checks in checks_by_rule.items():
            for c in checks:
                actual_str = f"{c['actual']:+.4f}" if c["actual"] is not None else "veri yok"
                met_str = "✓ AKTIF" if c["met"] else "✗ aktif değil"
                lines.append(
                    f"- [{rule_id}] {c['condition_key']} {c['operator']} {c['threshold']}"
                    f" | gerçek: {actual_str} | {met_str}"
                )
        return "\n".join(lines)

    @staticmethod
    def _fmt_initial_impact(bist_impact_json: str) -> str:
        try:
            impact = json.loads(bist_impact_json or "{}")
        except json.JSONDecodeError:
            return "Önceki analiz mevcut değil."
        overall = impact.get("overall", "—")
        sectors = impact.get("sectors", [])
        lines = [f"Genel yön: {overall}"]
        for s in sectors:
            tickers = ", ".join(s.get("stocks", []))
            lines.append(f"  • {s['sector']} [{tickers}] → {s.get('direction','?')}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_market(market_by_ticker: dict[str, Any]) -> str:
        if not market_by_ticker:
            return "Piyasa verisi mevcut değil."
        lines = []
        for ticker, row in market_by_ticker.items():
            chg = f"{row['change_pct']:+.2f}%" if row["change_pct"] is not None else "N/A"
            close = row["close"] if row["close"] is not None else "—"
            lines.append(f"- {ticker}: {close} ({chg})")
        return "\n".join(lines)

    # ── JSON ayrıştırma ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise json.JSONDecodeError("JSON bulunamadı", raw, 0)

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Belirtilen tarih için tüm sinyalleri derinlemesine analiz eder.

        Returns:
            Eklenen content satırlarının ID listesi.
        """
        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        signals = db.fetchall(
            "SELECT * FROM signals WHERE date=? ORDER BY rank ASC LIMIT ?",
            (date_str, self._max_signals),
        )
        if not signals:
            logger.info("[AnalystAgent] %s tarihinde işlenecek sinyal yok", date_str)
            return []

        # Piyasa verisini ticker → row sözlüğüne dönüştür
        market_rows = db.fetchall(
            "SELECT ticker, close, change_pct FROM market_snapshots WHERE date=?",
            (date_str,),
        )
        market_by_ticker: dict[str, Any] = {row["ticker"]: row for row in market_rows}

        content_ids: list[int] = []

        for signal in signals:
            rule_ids: list[str] = json.loads(signal["transmission_rule_ids"] or "[]")
            active_rules = [self._rules[rid] for rid in rule_ids if rid in self._rules]

            # Her aktif kural için trigger koşullarını değerlendir
            checks_by_rule: dict[str, list[dict]] = {}
            for rule in active_rules:
                checks = self._evaluate_conditions(rule, market_by_ticker)
                if checks:
                    checks_by_rule[rule["id"]] = checks

            any_condition_active = any(
                c["met"]
                for checks in checks_by_rule.values()
                for c in checks
            )

            prompt = _USER_PROMPT.format(
                headline=signal["headline"],
                what_happened=signal["what_happened"],
                why_it_matters=signal["why_it_matters"],
                bias=signal["bias"] or "neutral",
                confidence=float(signal["confidence"] or 0.5),
                initial_impact=self._fmt_initial_impact(signal["bist_impact_json"] or "{}"),
                trigger_checks=self._fmt_trigger_checks(checks_by_rule),
                market_data=self._fmt_market(market_by_ticker),
            )

            try:
                resp = self._llm.call(
                    agent="analyst",
                    messages=[{"role": "user", "content": prompt}],
                    system=_SYSTEM_PROMPT,
                )
                parsed = self._parse_json(resp.content)

            except BudgetExceeded:
                logger.warning(
                    "[AnalystAgent] Token bütçesi aşıldı — %d sinyal işlenemedi",
                    len(signals) - signals.index(signal),
                )
                break

            except json.JSONDecodeError as exc:
                logger.error(
                    "[AnalystAgent] Sinyal %d: LLM yanıtı JSON değil: %s",
                    signal["id"],
                    exc,
                )
                continue

            except Exception as exc:
                logger.error(
                    "[AnalystAgent] Sinyal %d: LLM çağrısı başarısız: %s",
                    signal["id"],
                    exc,
                )
                continue

            # Olasılıkların toplamı 1.0 olmalı — yumuşak normalize
            scenarios = parsed.get("scenarios", {})
            total_prob = sum(
                s.get("probability", 0.0) for s in scenarios.values()
            )
            if total_prob > 0:
                for s in scenarios.values():
                    s["probability"] = round(s["probability"] / total_prob, 4)

            body = json.dumps(
                {
                    "signal_id": signal["id"],
                    "trigger_conditions_active": any_condition_active,
                    "scenarios": scenarios,
                    "time_horizon": parsed.get("time_horizon", "ayni_gun"),
                    "key_risk": parsed.get("key_risk", ""),
                    "key_opportunity": parsed.get("key_opportunity", ""),
                },
                ensure_ascii=False,
                indent=2,
            )

            content_id = db.insert_content({
                "date": date_str,
                "platform": "analyst_brief",
                "title": signal["headline"],
                "body": body,
                "word_count": None,
                # analyst_brief dahili belgedir — SPK uyum denetimi gerekmez
                "compliance_passed": 1,
                "compliance_warnings": json.dumps([]),
                "prompt_version_id": None,
            })
            content_ids.append(content_id)
            logger.info(
                "[AnalystAgent] Brief #%d eklendi (sinyal=%d, koşul_aktif=%s, horizon=%s)",
                content_id,
                signal["id"],
                any_condition_active,
                parsed.get("time_horizon", "?"),
            )

        return content_ids
