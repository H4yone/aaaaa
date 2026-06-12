"""
TikTok Publisher — tiktok_1..4 içeriklerini TikTok Content Posting API v2 ile yükler.

Env:
  TIKTOK_ACCESS_TOKEN   → OAuth2 user access token
  TIKTOK_CLIENT_KEY     → uygulama client key (URL oluşturmak için)
  OUTPUT_DIR            → video dosyaları dizini

Video dosyası konvansiyonu:
  {OUTPUT_DIR}/{YYYY-MM-DD}/{platform}_{content_id}.mp4

Video yoksa (Gün 10'da TTS + ffmpeg ile üretilecek) o satır atlanır.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://open.tiktokapis.com/v2"
_TIKTOK_PLATFORMS = ("tiktok_1", "tiktok_2", "tiktok_3", "tiktok_4")


class TikTokPublisher:
    """
    TikTok Content Posting API v2 wrapper.

    Testlerde `session` parametresine mock geçilir.
    """

    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    def _get_session(self) -> requests.Session:
        if self._session is None:
            token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            })
            self._session = s
        return self._session

    # ── Yükleme akışı ─────────────────────────────────────────────────────────

    def _init_upload(self, title: str, video_size: int) -> dict:
        """TikTok upload oturumu başlatır. upload_url ve publish_id döner."""
        chunk_size = min(video_size, 10 * 1024 * 1024)  # max 10 MB chunk
        payload = {
            "post_info": {
                "title": title[:150],
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": 1,
            },
        }
        resp = self._get_session().post(
            f"{_API_BASE}/post/publish/video/init/",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"]  # {"upload_url": ..., "publish_id": ...}

    def _upload_chunk(self, upload_url: str, video_bytes: bytes, video_size: int) -> None:
        """Video byte'larını TikTok upload URL'ine yükler."""
        headers = {
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
            "Content-Type": "video/mp4",
        }
        resp = self._get_session().put(upload_url, data=video_bytes,
                                       headers=headers, timeout=120)
        resp.raise_for_status()

    def upload_video(self, title: str, video_path: Path) -> str:
        """
        Videoyu TikTok'a yükler.

        Returns:
            TikTok video URL'i (https://www.tiktok.com/@user/video/<publish_id>)
        """
        video_bytes = video_path.read_bytes()
        video_size = len(video_bytes)

        init_data = self._init_upload(title, video_size)
        upload_url: str = init_data["upload_url"]
        publish_id: str = str(init_data["publish_id"])

        self._upload_chunk(upload_url, video_bytes, video_size)

        client_key = os.getenv("TIKTOK_CLIENT_KEY", "unknown")
        url = f"https://www.tiktok.com/@{client_key}/video/{publish_id}"
        logger.info("[TikTokPublisher] Yüklendi: %s → %s", title[:50], url)
        return url

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Onaylanmış TikTok içeriklerini yükler.

        Returns:
            Yayınlanan content satırlarının ID listesi.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
        db = get_db()

        rows = db.fetchall(
            f"""SELECT * FROM content
                WHERE date=? AND platform IN {tuple(_TIKTOK_PLATFORMS)!r}
                  AND compliance_passed=1 AND human_approved=1
                  AND published_at IS NULL""",
            (date_str,),
        )

        if not rows:
            logger.info("[TikTokPublisher] %s tarihinde yüklenecek TikTok içeriği yok", date_str)
            return []

        published_ids: list[int] = []

        for row in rows:
            video_path = output_dir / date_str / f"{row['platform']}_{row['id']}.mp4"
            if not video_path.exists():
                logger.warning(
                    "[TikTokPublisher] Video dosyası yok, atlanıyor: %s "
                    "(TTS+ffmpeg ile üretilmesi gerekiyor)",
                    video_path,
                )
                continue

            try:
                url = self.upload_video(title=row["title"] or "BIST Analizi", video_path=video_path)
            except Exception as exc:
                logger.error("[TikTokPublisher] İçerik %d yükleme hatası: %s", row["id"], exc)
                continue

            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE content SET published_at=?, publish_url=? WHERE id=?",
                (now_utc, url, row["id"]),
            )
            published_ids.append(row["id"])

        return published_ids
