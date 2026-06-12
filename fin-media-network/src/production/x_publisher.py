"""
X (Twitter) Publisher — x_thread içeriklerini tweet zinciri olarak yayınlar.

Gereksinimler (env):
  X_API_KEY, X_API_SECRET        → OAuth1 consumer credentials
  X_ACCESS_TOKEN, X_ACCESS_SECRET → OAuth1 user tokens
  X_BEARER_TOKEN                  → sadece okuma (opsiyonel)

İçerik formatı (content.body):
  {"tweets": ["tweet1", "tweet2", ...]}

Her tweet ≤280 karakter. İlk tweet standalone, sonrakiler reply zinciri.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


class XPublisher:
    """
    Tweepy v4 üzerinden X thread yayınlar.

    Testlerde `client` parametresine mock geçilir;
    prodüksiyonda None bırakılır ve env'den build edilir.
    """

    def __init__(self, client=None) -> None:
        self._client = client

    # ── Tweepy client kurulumu ────────────────────────────────────────────────

    def _build_client(self):
        import tweepy

        return tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_SECRET"),
            wait_on_rate_limit=True,
        )

    def _get_client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ── Thread yayınlama ──────────────────────────────────────────────────────

    def post_thread(self, tweets: list[str]) -> tuple[str, str]:
        """
        Tweet listesini reply zinciri olarak yayınlar.

        Returns:
            (first_tweet_id, thread_url)
        """
        client = self._get_client()
        first_id: str | None = None
        prev_id: str | None = None

        for i, text in enumerate(tweets):
            text = text[:280]
            kwargs: dict = {"text": text}
            if prev_id:
                kwargs["in_reply_to_tweet_id"] = prev_id

            response = client.create_tweet(**kwargs)
            tweet_id = str(response.data["id"])

            if i == 0:
                first_id = tweet_id
            prev_id = tweet_id
            logger.debug("[XPublisher] Tweet %d/%d yayınlandı: %s", i + 1, len(tweets), tweet_id)

        username = os.getenv("X_USERNAME", "user")
        url = f"https://x.com/{username}/status/{first_id}"
        logger.info("[XPublisher] Thread tamamlandı: %s", url)
        return first_id, url  # type: ignore[return-value]

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def run(self, run_date: date | None = None) -> list[int]:
        """
        Onaylanmış x_thread içeriklerini yayınlar.

        Returns:
            Yayınlanan content satırlarının ID listesi.
        """
        from src.db.database import get_db

        if run_date is None:
            run_date = date.today()
        date_str = run_date.isoformat()
        db = get_db()

        rows = db.fetchall(
            """SELECT * FROM content
               WHERE date=? AND platform='x_thread'
                 AND compliance_passed=1 AND human_approved=1
                 AND published_at IS NULL""",
            (date_str,),
        )

        if not rows:
            logger.info("[XPublisher] %s tarihinde yayınlanacak X thread yok", date_str)
            return []

        published_ids: list[int] = []

        for row in rows:
            try:
                data = json.loads(row["body"])
                tweets: list[str] = data.get("tweets", [])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.error("[XPublisher] İçerik %d body parse hatası: %s", row["id"], exc)
                continue

            if not tweets:
                logger.warning("[XPublisher] İçerik %d: tweet listesi boş", row["id"])
                continue

            try:
                _, url = self.post_thread(tweets)
            except Exception as exc:
                logger.error("[XPublisher] İçerik %d yayın hatası: %s", row["id"], exc)
                continue

            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            db.execute(
                "UPDATE content SET published_at=?, publish_url=? WHERE id=?",
                (now_utc, url, row["id"]),
            )
            published_ids.append(row["id"])
            logger.info("[XPublisher] İçerik %d yayınlandı → %s", row["id"], url)

        return published_ids
