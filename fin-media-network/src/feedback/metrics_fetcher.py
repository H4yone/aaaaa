"""
Performans metriklerini YouTube, TikTok ve X API'lerinden çeker.

Env:
  YOUTUBE_API_KEY       → YouTube Data API v3 erişimi
  TIKTOK_ACCESS_TOKEN   → TikTok API token
  TWITTER_BEARER_TOKEN  → Twitter v2 metrics

Yayınlanmış her içerik için publish_url'den platform ID'si çıkarılır,
ilgili API çağrılır ve sonuç `performance` tablosuna yazılır.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_TIKTOK_PLATFORMS = {"tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4"}


def _youtube_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _tiktok_video_id(url: str) -> str | None:
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else None


def _twitter_tweet_id(url: str) -> str | None:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


class MetricsFetcher:
    """
    Platform API'lerinden performans metriklerini çeker.

    Testlerde `youtube_service`, `x_client`, `tiktok_session` parametreleriyle
    mock geçilir.
    """

    def __init__(
        self,
        youtube_service: Any | None = None,
        x_client: Any | None = None,
        tiktok_session: Any | None = None,
    ) -> None:
        self._youtube = youtube_service
        self._x = x_client
        self._tiktok = tiktok_session

    # ── Lazy API başlatma ─────────────────────────────────────────────────────

    def _get_youtube(self):
        if self._youtube is None:
            from googleapiclient.discovery import build
            self._youtube = build(
                "youtube", "v3",
                developerKey=os.getenv("YOUTUBE_API_KEY", ""),
            )
        return self._youtube

    def _get_x(self):
        if self._x is None:
            import tweepy
            self._x = tweepy.Client(
                bearer_token=os.getenv("TWITTER_BEARER_TOKEN", ""),
                wait_on_rate_limit=True,
            )
        return self._x

    def _get_tiktok(self):
        if self._tiktok is None:
            import requests
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {os.getenv('TIKTOK_ACCESS_TOKEN', '')}",
                "Content-Type": "application/json; charset=UTF-8",
            })
            self._tiktok = s
        return self._tiktok

    # ── Platform metrik çekicileri ────────────────────────────────────────────

    def _fetch_youtube_metrics(self, video_id: str) -> dict:
        resp = self._get_youtube().videos().list(
            part="statistics",
            id=video_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return {}
        stats = items[0].get("statistics", {})
        views = int(stats.get("viewCount", 0) or 0)
        likes = int(stats.get("likeCount", 0) or 0)
        comments = int(stats.get("commentCount", 0) or 0)
        eng = (likes + comments) / views if views > 0 else 0.0
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": None,
            "engagement_rate": round(eng, 6),
        }

    def _fetch_x_metrics(self, tweet_id: str) -> dict:
        tweet = self._get_x().get_tweet(
            tweet_id,
            tweet_fields=["public_metrics"],
        )
        m = tweet.data.public_metrics
        views = m.get("impression_count", 0) or 0
        likes = m.get("like_count", 0) or 0
        comments = m.get("reply_count", 0) or 0
        shares = m.get("retweet_count", 0) or 0
        eng = (likes + comments + shares) / views if views > 0 else 0.0
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement_rate": round(eng, 6),
        }

    def _fetch_tiktok_metrics(self, video_id: str) -> dict:
        resp = self._get_tiktok().post(
            "https://open.tiktokapis.com/v2/video/query/",
            json={
                "filters": {"video_ids": [video_id]},
                "fields": ["like_count", "comment_count", "share_count", "view_count"],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        videos = data.get("videos", [])
        if not videos:
            return {}
        v = videos[0]
        views = int(v.get("view_count", 0) or 0)
        likes = int(v.get("like_count", 0) or 0)
        comments = int(v.get("comment_count", 0) or 0)
        shares = int(v.get("share_count", 0) or 0)
        eng = (likes + comments + shares) / views if views > 0 else 0.0
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement_rate": round(eng, 6),
        }

    # ── Ana çalışma ───────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Belirtilen tarih için yayınlanmış tüm içeriklerin metriklerini çeker.

        Returns:
            Eklenen performance satırlarının ID listesi.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        rows = db.fetchall(
            """SELECT id, platform, publish_url FROM content
               WHERE date=? AND published_at IS NOT NULL
                 AND publish_url IS NOT NULL""",
            (date_str,),
        )

        if not rows:
            logger.info("[MetricsFetcher] %s için yayınlanmış içerik yok", date_str)
            return []

        inserted_ids: list[int] = []

        for row in rows:
            platform: str = row["platform"]
            url: str = row["publish_url"]
            content_id: int = row["id"]

            try:
                metrics = self._metrics_for(platform, url)
            except Exception as exc:
                logger.error(
                    "[MetricsFetcher] İçerik %d metrik hatası: %s", content_id, exc
                )
                continue

            if not metrics:
                logger.warning(
                    "[MetricsFetcher] İçerik %d için metrik alınamadı (boş yanıt)", content_id
                )
                continue

            perf_id = db.execute(
                """INSERT INTO performance
                   (content_id, platform, views, likes, comments, shares,
                    watch_time_sec, retention_pct, ctr, engagement_rate, impressions)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    content_id,
                    platform,
                    metrics.get("views"),
                    metrics.get("likes"),
                    metrics.get("comments"),
                    metrics.get("shares"),
                    metrics.get("watch_time_sec"),
                    metrics.get("retention_pct"),
                    metrics.get("ctr"),
                    metrics.get("engagement_rate"),
                    metrics.get("impressions"),
                ),
            ).lastrowid
            inserted_ids.append(perf_id)
            logger.info(
                "[MetricsFetcher] İçerik %d (%s) → görüntüleme=%s etkileşim=%.4f",
                content_id, platform,
                metrics.get("views"), metrics.get("engagement_rate") or 0.0,
            )

        return inserted_ids

    def _metrics_for(self, platform: str, url: str) -> dict:
        if platform == "youtube":
            vid = _youtube_video_id(url)
            if not vid:
                raise ValueError(f"YouTube video ID çıkarılamadı: {url}")
            return self._fetch_youtube_metrics(vid)

        if platform in _TIKTOK_PLATFORMS:
            vid = _tiktok_video_id(url)
            if not vid:
                raise ValueError(f"TikTok video ID çıkarılamadı: {url}")
            return self._fetch_tiktok_metrics(vid)

        if platform in ("x_thread", "x_brief", "x_closing"):
            tid = _twitter_tweet_id(url)
            if not tid:
                raise ValueError(f"Twitter tweet ID çıkarılamadı: {url}")
            return self._fetch_x_metrics(tid)

        logger.warning("[MetricsFetcher] Bilinmeyen platform: %s", platform)
        return {}
