from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from src.db.database import get_db

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
_WEIGHTS_PATH = Path(__file__).parent.parent.parent / "config" / "source_weights.yaml"


class RSSFetcher:
    def __init__(
        self,
        config_path: str | Path | None = None,
        source_weights_path: str | Path | None = None,
        feedparser_module: Any | None = None,
    ) -> None:
        self._cfg_path = Path(config_path) if config_path else _CONFIG_PATH
        self._weights_path = Path(source_weights_path) if source_weights_path else _WEIGHTS_PATH
        self._feedparser = feedparser_module

        # Ayarları yükle
        with open(self._cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self._feeds: dict[str, list[dict]] = cfg.get("rss_feeds", {})

        # Kaynak ağırlık katmanlarını yükle
        with open(self._weights_path, encoding="utf-8") as f:
            weights = yaml.safe_load(f)
        self._tiers: dict[str, dict] = {
            k: v for k, v in weights.items() if k.startswith("tier_")
        }

    def _get_feedparser(self) -> Any:
        # feedparser modülünü tembel yükle
        if self._feedparser is None:
            import feedparser
            self._feedparser = feedparser
        return self._feedparser

    def _source_weight(self, source_url: str) -> float:
        # URL'den domain çıkar, tier listelerinde ara
        try:
            domain = urlparse(source_url).netloc.lower().lstrip("www.")
        except Exception:
            domain = ""

        for tier_key in ("tier_elite", "tier_high", "tier_medium", "tier_low"):
            tier = self._tiers.get(tier_key, {})
            for src in tier.get("sources", []):
                if domain == src or domain.endswith("." + src):
                    return float(tier.get("weight", 0.4))

        return float(self._tiers.get("tier_unknown", {}).get("weight", 0.4))

    def _url_hash(self, url: str) -> str:
        return hashlib.sha256(url.strip().encode()).hexdigest()

    def _parse_entry(self, entry: Any, feed_name: str, feed_weight: float) -> dict | None:
        url = entry.get("link", "")
        title = entry.get("title", "")

        # Başlık veya URL yoksa atla
        if not title or not url:
            return None

        summary = entry.get("summary", "")

        # Yayın tarihini UTC ISO formatına çevir
        published_at: str | None = None
        pt = entry.get("published_parsed")
        if pt is not None:
            try:
                published_at = datetime(*pt[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                published_at = None

        # Kaynak adı: feedparser source varsa kullan, yoksa feed_name
        source_obj = getattr(entry, "source", None) or entry.get("source", {})
        if isinstance(source_obj, dict):
            source_name = source_obj.get("title", feed_name)
        else:
            source_name = getattr(source_obj, "title", feed_name) if source_obj else feed_name

        # Kaynak URL'den domain
        try:
            parsed = urlparse(url)
            source_url = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            source_url = url

        raw_json = json.dumps({"title": title, "link": url})

        return {
            "url_hash": self._url_hash(url),
            "url": url,
            "title": title,
            "summary": summary,
            "source_name": source_name,
            "source_url": source_url,
            "published_at": published_at,
            "feed_name": feed_name,
            "raw_json": raw_json,
        }

    def run(self, run_date: str | None = None) -> list[int]:
        db = get_db()
        fp = self._get_feedparser()
        inserted_ids: list[int] = []

        # Her feed grubundaki her feed'i gez
        for _group, feed_list in self._feeds.items():
            for feed_cfg in feed_list:
                feed_url: str = feed_cfg.get("url", "")
                feed_name: str = feed_cfg.get("name", "unknown")
                feed_weight: float = float(feed_cfg.get("weight", 0.5))

                try:
                    parsed = fp.parse(feed_url)
                    entries = parsed.get("entries", [])
                except Exception as exc:
                    logger.warning("[RSSFetcher] %s feed parse hatası: %s", feed_name, exc)
                    continue

                valid_rows: list[dict] = []
                for entry in entries:
                    row = self._parse_entry(entry, feed_name, feed_weight)
                    if row is not None:
                        valid_rows.append(row)

                new_count = 0
                for row in valid_rows:
                    try:
                        cursor = db.execute(
                            """
                            INSERT OR IGNORE INTO raw_news
                              (url_hash, url, title, summary, source_name, source_url,
                               published_at, feed_name, raw_json)
                            VALUES
                              (:url_hash, :url, :title, :summary, :source_name, :source_url,
                               :published_at, :feed_name, :raw_json)
                            """,
                            row,
                        )
                        last = cursor.lastrowid
                        if last:
                            inserted_ids.append(last)
                            new_count += 1
                    except Exception as exc:
                        logger.warning("[RSSFetcher] %s satır ekleme hatası: %s", feed_name, exc)

                logger.info(
                    "[RSSFetcher] %s: %d makale, %d yeni",
                    feed_name,
                    len(entries),
                    new_count,
                )

        return inserted_ids
