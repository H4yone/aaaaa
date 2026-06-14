"""
Narrative Writer — en yüksek sıralı sinyalden platform içeriği üretir.

Platformlar:
  youtube   → ~1000 kelime, başlık + gövde + disclaimer
  tiktok_1..4 → ~100 kelime, her biri farklı açıdan hook + özet (tek LLM çağrısı)
  x_thread  → 5–8 tweet ≤280 karakter, body'de JSON {"tweets": [...]}

Akış:
  1. Günün rank=1 sinyalini al
  2. Sinyalin analyst_brief'ini bul (varsa)
  3. Her platform için LLM çağrısı
  4. Her çıktıyı ComplianceChecker'dan geçir
  5. passed=1 ise content tablosuna yaz
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.content.compliance_checker import ComplianceChecker
from src.db.database import get_db
from src.intelligence.llm_client import BudgetExceeded, LLMClient

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

_SYSTEM = """\
Sen iki sunuculu bir Türk finansal YouTube/TikTok kanalının senaryo yazarısın.
- SUNUCU: Haberleri tanıtır, soruları yönlendirir, izleyiciyle bağ kurar.
- ANALİST: Piyasa dinamiklerini, BIST etkilerini ve verileri derinlemesine açıklar.
Her konuşma satırı [SUNUCU] veya [ANALİST] etiketiyle başlar.
Türkçe yaz. Anlaşılır, bilgilendirici, tarafsız ol.
Yatırım tavsiyesi verme — sadece analiz et ve bilgilendir.
Senaryoyu YALNIZCA sana verilen güncel haber verisine dayandır; uydurma olay,
tarih veya rakam ekleme. Konuyu izleyiciye "bugünün piyasa gündemi" olarak,
güncel ve zamanında sun.
Çıktın her zaman istenen formatta olsun.\
"""

# ── Platform prompt'ları ──────────────────────────────────────────────────────

_YT_PROMPT = """\
Aşağıdaki finansal analizi YouTube videosu için SUNUCU ve ANALİST arasında \
diyalog formatında senaryo olarak üret.

## Kaynak Sinyal
Başlık      : {headline}
Ne oldu     : {what_happened}
Neden önemli: {why_it_matters}
Genel yön   : {bias} (güven: {confidence:.0%})

## Senaryo Analizi
{scenarios}

## Format Kuralları
- Her satır [SUNUCU] veya [ANALİST] etiketiyle başlasın
- SUNUCU: izleyiciyi selamlar, haberi tanıtır, sorular sorar, uğurlar
- ANALİST: verileri, BIST etkilerini ve piyasa dinamiklerini açıklar
- Senaryo yalnızca yukarıdaki güncel haber verisine dayansın; başka olay,
  tarih veya rakam uydurma. Konuyu "bugünün gündemi" olarak çerçevele
- Markdown kullanma, her satır etiketle başlasın

## Zorunlu İskelet — TAM OLARAK bu 7 repliği üret, fazlasını ASLA ekleme
Her replik UZUN ve DOLU olsun (3–5 cümle); toplam {min_words}–{max_words} kelime.
1) [SUNUCU] Açılış selamı + haberi tanıt + analiste ilk soru
2) [ANALİST] Ne olduğunu ve neden önemli olduğunu derinlemesine açıkla
3) [SUNUCU] Konuyu BIST/sektör etkisine bağlayan ikinci soru
4) [ANALİST] BIST etkileri, sektörler ve piyasa dinamiklerini verilerle açıkla
5) [SUNUCU] Riskler ve dikkat edilmesi gerekenlere dair üçüncü soru
6) [ANALİST] Senaryoları, riskleri ve izlenecek başlıkları özetle
7) [SUNUCU] Kapanış + zorunlu disclaimer: "Bu içerik yatırım tavsiyesi değildir."\
"""

_TIKTOK_PROMPT = """\
Aşağıdaki haberi 4 farklı TikTok videosu için {min_words}–{max_words} kelimelik \
SUNUCU–ANALİST diyalog scriptlerine dönüştür.
Her script: dikkat çekici hook + ana bilgi + kapanış.
Her script farklı bir açıyı vurgulasın (genel etki / bankacılık / döviz / fırsat-risk).
Her konuşma satırı [SUNUCU] veya [ANALİST] etiketiyle başlasın.

## Kaynak
{headline}

{what_happened}

{why_it_matters}

## Çıktı — sadece aşağıdaki JSON'u döndür:
{{
  "tiktok_1": "[SUNUCU] ... [ANALİST] ...",
  "tiktok_2": "[SUNUCU] ... [ANALİST] ...",
  "tiktok_3": "[SUNUCU] ... [ANALİST] ...",
  "tiktok_4": "[SUNUCU] ... [ANALİST] ..."
}}\
"""

_X_PROMPT = """\
Aşağıdaki analizi Twitter/X thread'ine dönüştür.
- 5–8 tweet, her biri ≤280 karakter
- İlk tweet: dikkat çekici hook
- Son tweet: "Bu içerik yatırım tavsiyesi değildir." içersin

## Kaynak
{headline}

{what_happened}

{why_it_matters}

## Çıktı — sadece aşağıdaki JSON'u döndür:
{{
  "tweets": ["<tweet1>", "<tweet2>", ...]
}}\
"""


def _fmt_scenarios(analyst_brief_body: str | None) -> str:
    if not analyst_brief_body:
        return "Senaryo analizi mevcut değil."
    try:
        data = json.loads(analyst_brief_body)
        scenarios = data.get("scenarios", {})
        lines = []
        for name, s in scenarios.items():
            prob = s.get("probability", 0)
            desc = s.get("description", "")
            lines.append(f"- {name.upper()} (%{prob:.0%}): {desc}")
        return "\n".join(lines) if lines else "Senaryo verisi boş."
    except (json.JSONDecodeError, TypeError):
        return "Senaryo analizi okunamadı."


def _parse_json(raw: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(raw[start : end + 1])
    raise json.JSONDecodeError("JSON bulunamadı", raw, 0)


class NarrativeWriter:
    """Sinyal → platform içeriği dönüşümünü yönetir."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        compliance_checker: ComplianceChecker | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._compliance = compliance_checker or ComplianceChecker()
        cfg_path = Path(config_path) if config_path else _CONFIG_PATH
        content_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["content"]
        self._yt_min: int = content_cfg["youtube_min_words"]
        self._yt_max: int = content_cfg["youtube_max_words"]
        self._tt_min: int = content_cfg["tiktok_min_words"]
        self._tt_max: int = content_cfg["tiktok_max_words"]

    # ── İçerik üretimi ────────────────────────────────────────────────────────

    def _write_youtube(self, signal: Any, brief_body: str | None) -> str | None:
        """YouTube metni üretir. Başarısızsa None döner."""
        prompt = _YT_PROMPT.format(
            headline=signal["headline"],
            what_happened=signal["what_happened"],
            why_it_matters=signal["why_it_matters"],
            bias=signal["bias"] or "neutral",
            confidence=float(signal["confidence"] or 0.5),
            scenarios=_fmt_scenarios(brief_body),
            min_words=self._yt_min,
            max_words=self._yt_max,
        )
        resp = self._llm.call(
            agent="narrative",
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
        )
        return resp.content

    def _write_tiktok(self, signal: Any) -> dict[str, str] | None:
        """4 TikTok scripti üretir. JSON dict döner."""
        prompt = _TIKTOK_PROMPT.format(
            headline=signal["headline"],
            what_happened=signal["what_happened"],
            why_it_matters=signal["why_it_matters"],
            min_words=self._tt_min,
            max_words=self._tt_max,
        )
        resp = self._llm.call(
            agent="narrative",
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
        )
        return _parse_json(resp.content)

    def _write_x_thread(self, signal: Any) -> list[str] | None:
        """X thread tweetlerini üretir. Liste döner."""
        prompt = _X_PROMPT.format(
            headline=signal["headline"],
            what_happened=signal["what_happened"],
            why_it_matters=signal["why_it_matters"],
        )
        resp = self._llm.call(
            agent="narrative",
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
        )
        parsed = _parse_json(resp.content)
        return parsed.get("tweets", [])

    # ── Compliance + DB kayıt ─────────────────────────────────────────────────

    def _save(self, db: Any, date_str: str, platform: str,
              title: str, body: str) -> int | None:
        """Compliance geçerse content tablosuna yazar; aksi halde None döner."""
        result = self._compliance.check(body)
        if not result.passed:
            logger.warning(
                "[NarrativeWriter] %s compliance başarısız: %s",
                platform,
                result.warnings,
            )
            return None

        content_id = db.insert_content({
            "date": date_str,
            "platform": platform,
            "title": title,
            "body": result.body,
            "word_count": len(result.body.split()),
            "compliance_passed": 1,
            "compliance_warnings": json.dumps(result.warnings),
            "prompt_version_id": None,
        })
        logger.info(
            "[NarrativeWriter] %s kaydedildi (id=%d, uyarı=%d)",
            platform,
            content_id,
            len(result.warnings),
        )
        return content_id

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Günün rank=1 sinyalinden tüm platform içeriklerini üretir.

        Returns:
            Eklenen content satırlarının ID listesi (compliance geçenler).
        """
        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        signal = db.fetchone(
            "SELECT * FROM signals WHERE date=? ORDER BY rank ASC LIMIT 1",
            (date_str,),
        )
        if not signal:
            logger.info("[NarrativeWriter] %s tarihinde sinyal yok", date_str)
            return []

        # analyst_brief varsa al
        brief_row = db.fetchone(
            "SELECT body FROM content WHERE date=? AND platform='analyst_brief'"
            " AND title=? LIMIT 1",
            (date_str, signal["headline"]),
        )
        brief_body: str | None = brief_row["body"] if brief_row else None

        content_ids: list[int] = []

        # ── YouTube ──────────────────────────────────────────────────────────
        try:
            yt_body = self._write_youtube(signal, brief_body)
            if yt_body:
                cid = self._save(db, date_str, "youtube", signal["headline"], yt_body)
                if cid:
                    content_ids.append(cid)
        except BudgetExceeded:
            logger.warning("[NarrativeWriter] Bütçe aşıldı, YouTube sonrası durdu")
            return content_ids
        except Exception as exc:
            logger.error("[NarrativeWriter] YouTube hatası: %s", exc)

        # ── TikTok (4 adet, tek LLM çağrısı) ────────────────────────────────
        try:
            tt_scripts = self._write_tiktok(signal)
            if tt_scripts:
                for key in ("tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4"):
                    body = tt_scripts.get(key, "")
                    if not body:
                        continue
                    cid = self._save(db, date_str, key, signal["headline"], body)
                    if cid:
                        content_ids.append(cid)
        except BudgetExceeded:
            logger.warning("[NarrativeWriter] Bütçe aşıldı, TikTok sonrası durdu")
            return content_ids
        except (json.JSONDecodeError, Exception) as exc:
            logger.error("[NarrativeWriter] TikTok hatası: %s", exc)

        # ── X Thread ─────────────────────────────────────────────────────────
        try:
            tweets = self._write_x_thread(signal)
            if tweets:
                # ≤280 karakter kısıtını uygula
                tweets = [t[:280] for t in tweets]
                # Doğrulama: son tweet'te disclaimer yoksa ekle
                disclaimer = "Bu içerik yatırım tavsiyesi değildir."
                if not any("yatırım tavsiyesi" in t.lower() for t in tweets):
                    tweets.append(disclaimer)
                body = json.dumps({"tweets": tweets}, ensure_ascii=False)
                cid = self._save(db, date_str, "x_thread", signal["headline"], body)
                if cid:
                    content_ids.append(cid)
        except BudgetExceeded:
            logger.warning("[NarrativeWriter] Bütçe aşıldı, X thread sonrası durdu")
        except (json.JSONDecodeError, Exception) as exc:
            logger.error("[NarrativeWriter] X thread hatası: %s", exc)

        return content_ids
