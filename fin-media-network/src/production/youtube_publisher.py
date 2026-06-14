"""
YouTube Publisher — onaylanmış içerikleri YouTube kanalına yükler.

Gereksinimler:
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET  → OAuth2 credentials
  YOUTUBE_CHANNEL_ID                        → hedef kanal
  OUTPUT_DIR                                → video dosyaları dizini

Video dosyası konvansiyonu:
  {OUTPUT_DIR}/{YYYY-MM-DD}/youtube_{content_id}.mp4

Video dosyası yoksa (Gün 10'da TTS+ffmpeg ile üretilecek) o satır atlanır.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

# Yükleme kategorisi (Finance & Business)
_YT_CATEGORY_ID = "25"
_YT_DEFAULT_LANGUAGE = "tr"
_DEFAULT_PRIVACY = "unlisted"  # public | unlisted | private


def _load_privacy() -> str:
    import yaml
    try:
        cfg = yaml.safe_load(_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
        return (cfg.get("production") or {}).get("youtube_privacy", _DEFAULT_PRIVACY)
    except OSError:
        return _DEFAULT_PRIVACY


class YouTubePublisher:
    """
    YouTube Data API v3 üzerinden video yükler.

    Testlerde `service` parametresine mock geçilir;
    prodüksiyonda None bırakılır ve OAuth2 ile build edilir.
    """

    def __init__(self, service: Any | None = None, privacy: str | None = None) -> None:
        self._service = service
        self._privacy = privacy or _load_privacy()

    # ── OAuth2 / servis kurulumu ──────────────────────────────────────────────

    def _build_service(self) -> Any:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
        token_path = Path(os.getenv("YOUTUBE_TOKEN_PATH", "youtube_token.json"))

        if not token_path.exists():
            raise FileNotFoundError(
                f"YouTube OAuth2 token dosyası bulunamadı: {token_path}. "
                "İlk çalıştırmada 'python -m src.production.youtube_publisher --auth' ile yetkilendirin."
            )

        token_data = json.loads(token_path.read_text())
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        return build("youtube", "v3", credentials=creds)

    def _get_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    # ── Video yükleme ─────────────────────────────────────────────────────────

    def upload_video(
        self,
        title: str,
        description: str,
        video_path: Path,
        tags: list[str] | None = None,
        _media_upload_cls: Any | None = None,
    ) -> str:
        """
        Videoyu YouTube'a yükler.

        Returns:
            Yüklenen videonun URL'i (https://youtu.be/<id>)
        """
        if _media_upload_cls is None:
            from googleapiclient.http import MediaFileUpload
            _media_upload_cls = MediaFileUpload

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags or ["BIST", "borsa", "finans", "ekonomi"],
                "categoryId": _YT_CATEGORY_ID,
                "defaultLanguage": _YT_DEFAULT_LANGUAGE,
            },
            "status": {
                "privacyStatus": self._privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = _media_upload_cls(str(video_path), mimetype="video/mp4", resumable=True)
        request = self._get_service().videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = request.execute()
        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        logger.info("[YouTubePublisher] Yüklendi: %s → %s", title[:50], url)
        return url

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Onaylanmış YouTube içeriklerini yükler.

        Returns:
            Yayınlanan content satırlarının ID listesi.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        output_dir = Path(os.getenv("OUTPUT_DIR", "output"))

        rows = db.fetchall(
            """SELECT * FROM content
               WHERE date=? AND platform='youtube'
                 AND compliance_passed=1 AND human_approved=1
                 AND published_at IS NULL""",
            (date_str,),
        )

        if not rows:
            logger.info("[YouTubePublisher] %s tarihinde yüklenecek YouTube içeriği yok", date_str)
            return []

        published_ids: list[int] = []

        for row in rows:
            video_path = output_dir / date_str / f"youtube_{row['id']}.mp4"
            if not video_path.exists():
                logger.warning(
                    "[YouTubePublisher] Video dosyası yok, atlanıyor: %s "
                    "(Gün 10'da TTS+ffmpeg ile üretilecek)",
                    video_path,
                )
                continue

            try:
                url = self.upload_video(
                    title=row["title"] or "BIST Analizi",
                    description=row["body"],
                    video_path=video_path,
                )
            except Exception as exc:
                logger.error("[YouTubePublisher] İçerik %d yükleme hatası: %s", row["id"], exc)
                continue

            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE content SET published_at=?, publish_url=? WHERE id=?",
                (now_utc, url, row["id"]),
            )
            published_ids.append(row["id"])

        return published_ids


# ── CLI yetkilendirme ─────────────────────────────────────────────────────────

def _run_auth_flow() -> None:
    """İlk kurulumda OAuth2 token üretir ve kaydeder."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": os.getenv("YOUTUBE_CLIENT_ID", ""),
            "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", ""),
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    creds = flow.run_local_server(port=0)
    token_path = Path(os.getenv("YOUTUBE_TOKEN_PATH", "youtube_token.json"))
    token_path.write_text(json.dumps({
        "token": creds.token,
        "refresh_token": creds.refresh_token,
    }))
    print(f"Token kaydedildi: {token_path}")


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if "--auth" in sys.argv:
        _run_auth_flow()
    else:
        from src.db.database import get_db
        ids = YouTubePublisher().run()
        print(f"Yayınlanan: {ids}")
