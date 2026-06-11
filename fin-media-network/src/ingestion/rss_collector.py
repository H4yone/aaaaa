"""
LAYER 1 — RSS haber toplama
settings.yaml'daki tüm feed'leri feedparser ile çeker, raw_news'e yazar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import yaml

logger = logging.getLogger(__name__)

_REQUEST_DELAY = 1.0   # feed'ler arası bekleme (saniye)


def _load_settings() -> dict:
    with open(Path("config/settings.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── URL canonicalization ──────────────────────────────────────────────────────

def canonicalize_url(url: str) -> str:
    """utm_* ve izleme parametrelerini temizle, lowercase scheme+host."""
    try:
        parsed = urlparse(url)
        clean_params = [
            (k, v) for k, v in parse_qsl(parsed.query)
            if not k.startswith("utm_") and k not in ("ref", "source", "campaign")
        ]
        clean = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            query=urlencode(clean_params),
            fragment="",
        )
        return urlunparse(clean)
    except Exception:
        return url


def url_hash(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode()).hexdigest()[:32]


# ── Timestamp normalization ───────────────────────────────────────────────────

def parse_published(entry: dict) -> Optional[str]:
    """feedparser entry'sinden UTC datetime string üretir."""
    # feedparser parsed_published_parsed (time.struct_time) varsa kullan
    tp = entry.get("published_parsed") or entry.get("updated_parsed")
    if tp:
        try:
            dt = datetime(*tp[:6], tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    # Ham string
    raw = entry.get("published") or entry.get("updated", "")
    if raw:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(raw[:30], fmt).astimezone(timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
    return None


# ── Source name extraction ────────────────────────────────────────────────────

def extract_source_name(entry: dict, feed_url: str) -> str:
    """Haberin kaynak adını çıkar (varsa source tag, yoksa domain)."""
    source = entry.get("source", {})
    if isinstance(source, dict) and source.get("title"):
        return source["title"]
    try:
        return urlparse(feed_url).netloc.replace("www.", "")
    except Exception:
        return "unknown"


# ── Tek feed çekme ────────────────────────────────────────────────────────────

def fetch_feed(feed_url: str, feed_name: str, source_weight: float) -> list[dict]:
    """Bir RSS feed'ini çekip normalize edilmiş satır listesi döner."""
    try:
        parsed = feedparser.parse(feed_url)
    except Exception as e:
        logger.warning("feedparser hata [%s]: %s", feed_name, e)
        return []

    if parsed.bozo and not parsed.entries:
        logger.warning("Bozuk feed [%s]: %s", feed_name, parsed.get("bozo_exception", ""))
        return []

    rows: list[dict] = []
    for entry in parsed.entries:
        url = entry.get("link") or entry.get("id", "")
        if not url:
            continue

        title = entry.get("title", "").strip()
        if not title:
            continue

        summary = (entry.get("summary") or entry.get("description") or "").strip()
        # HTML tag'lerini kaba temizle
        summary = summary[:500] if summary else None

        source_name = extract_source_name(entry, feed_url)

        rows.append({
            "url_hash": url_hash(url),
            "url": url,
            "title": title,
            "summary": summary,
            "source_name": source_name,
            "source_url": feed_url,
            "published_at": parse_published(entry),
            "feed_name": feed_name,
            "raw_json": json.dumps({
                "id": entry.get("id"),
                "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
                "source_weight": source_weight,
            }),
        })

    logger.debug("Feed [%s]: %d haber", feed_name, len(rows))
    return rows


# ── Tüm feed'leri toplu çek ───────────────────────────────────────────────────

def fetch_all_feeds() -> list[dict]:
    settings = _load_settings()
    feeds_cfg: dict = settings.get("rss_feeds", {})

    all_rows: list[dict] = []
    total_feeds = 0

    for _category, feed_list in feeds_cfg.items():
        for feed_cfg in feed_list:
            url = feed_cfg["url"]
            name = feed_cfg["name"]
            weight = feed_cfg.get("weight", 0.5)
            rows = fetch_feed(url, name, weight)
            all_rows.extend(rows)
            total_feeds += 1
            time.sleep(_REQUEST_DELAY)

    logger.info("RSS: %d feed, %d haber toplandı", total_feeds, len(all_rows))
    return all_rows


def save_to_db(rows: list[dict]) -> int:
    from src.db.database import get_db
    db = get_db()
    inserted = db.insert_raw_news(rows)
    logger.info("raw_news: %d yeni kayıt (%d toplam gönderildi)", inserted, len(rows))
    return inserted


if __name__ == "__main__":
    import dotenv; dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from src.db.database import get_db
    get_db().init()
    rows = fetch_all_feeds()
    saved = save_to_db(rows)
    print(f"Toplanan: {len(rows)}, Yeni kaydedilen: {saved}")
    for r in rows[:5]:
        print(f"  [{r['source_name']}] {r['title'][:80]}")
