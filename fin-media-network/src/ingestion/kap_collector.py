"""
LAYER 1 — KAP (Kamuyu Aydınlatma Platformu) bildirimleri
RSS feed üzerinden BIST şirket özel durum açıklamaları.
KAP verisi yatırımcı kararları için kritik (source_weight = 1.0).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import feedparser

logger = logging.getLogger(__name__)

_KAP_RSS = "https://www.kap.org.tr/tr/rss"
_KAP_WEIGHT = 1.0

# BIST ticker eşleştirme için şirket adı → ticker sözlüğü (en sık görülenler)
_COMPANY_TICKER_MAP = {
    "garanti": "GARAN.IS",
    "akbank": "AKBNK.IS",
    "yapı kredi": "YKBNK.IS",
    "türk hava yolları": "THYAO.IS",
    "thy": "THYAO.IS",
    "pegasus": "PGSUS.IS",
    "tüpraş": "TUPRS.IS",
    "tupras": "TUPRS.IS",
    "aselsan": "ASELS.IS",
    "koç holding": "KCHOL.IS",
    "sabancı holding": "SAHOL.IS",
    "şişecam": "SISE.IS",
    "sisecam": "SISE.IS",
    "bist": "XU100.IS",
    "borsa istanbul": "XU100.IS",
}


def _extract_ticker_from_title(title: str) -> Optional[str]:
    """Başlıktaki şirket adından BIST ticker bulmaya çalışır."""
    title_lower = title.lower()
    for name, ticker in _COMPANY_TICKER_MAP.items():
        if name in title_lower:
            return ticker
    # KAP başlıklarında parantez içi kısa kod: "GARAN - Garanti BBVA ..."
    m = re.search(r"\b([A-Z]{3,6})\b", title)
    if m:
        return f"{m.group(1)}.IS"
    return None


def _parse_kap_entry(entry: dict) -> Optional[dict]:
    url = entry.get("link") or entry.get("id", "")
    if not url:
        return None
    title = entry.get("title", "").strip()
    if not title:
        return None

    summary = (entry.get("summary") or "").strip()[:500] or None

    # Timestamp
    tp = entry.get("published_parsed") or entry.get("updated_parsed")
    published_at = None
    if tp:
        try:
            dt = datetime(*tp[:6], tzinfo=timezone.utc)
            published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    ticker = _extract_ticker_from_title(title)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]

    return {
        "url_hash": url_hash,
        "url": url,
        "title": title,
        "summary": summary,
        "source_name": "kap.org.tr",
        "source_url": _KAP_RSS,
        "published_at": published_at,
        "feed_name": "kap_bildirimler",
        "raw_json": json.dumps({
            "source_weight": _KAP_WEIGHT,
            "ticker": ticker,
            "category": "kap_disclosure",
        }),
    }


def fetch_kap() -> list[dict]:
    """KAP RSS feed'ini çekip normalize edilmiş satır listesi döner."""
    try:
        parsed = feedparser.parse(_KAP_RSS)
    except Exception as e:
        logger.error("KAP RSS hata: %s", e)
        return []

    if parsed.bozo and not parsed.entries:
        logger.warning("KAP feed bozuk: %s", parsed.get("bozo_exception", ""))
        return []

    rows: list[dict] = []
    for entry in parsed.entries:
        row = _parse_kap_entry(entry)
        if row:
            rows.append(row)

    logger.info("KAP: %d bildiri toplandı", len(rows))
    return rows


def save_to_db(rows: list[dict]) -> int:
    from src.db.database import get_db
    db = get_db()
    inserted = db.insert_raw_news(rows)
    logger.info("kap raw_news: %d yeni kayıt", inserted)
    return inserted


if __name__ == "__main__":
    import dotenv; dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.db.database import get_db
    get_db().init()
    rows = fetch_kap()
    saved = save_to_db(rows)
    print(f"KAP: {len(rows)} bildiri, {saved} yeni kaydedildi")
    for r in rows[:5]:
        print(f"  {r['title'][:80]}")
