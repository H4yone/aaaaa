"""
XPublisher testleri — Tweepy client mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, call

import pytest

from src.db.database import reset_db
from src.production.x_publisher import XPublisher


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _mock_client(tweet_ids: list[str] | None = None) -> MagicMock:
    ids = tweet_ids or ["111", "222", "333"]
    client = MagicMock()
    client.create_tweet.side_effect = [
        MagicMock(data={"id": tid}) for tid in ids
    ]
    return client


def _seed_x_thread(db, date_str: str, tweets: list[str] | None = None,
                   compliance_passed: int = 1, human_approved: int = 1) -> int:
    if tweets is None:
        tweets = [
            "Fed faizi artırdı. BIST ne yapacak?",
            "Bankacılık sektörü baskı altında kalabilir.",
            "Bu içerik yatırım tavsiyesi değildir.",
        ]
    return db.insert_content({
        "date": date_str,
        "platform": "x_thread",
        "title": "Fed faiz analizi",
        "body": json.dumps({"tweets": tweets}),
        "word_count": 20,
        "compliance_passed": compliance_passed,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


# ── Thread yayınlama ──────────────────────────────────────────────────────────

class TestPostThread:
    def test_first_tweet_has_no_reply(self, monkeypatch):
        monkeypatch.setenv("X_USERNAME", "testuser")
        client = _mock_client(["t1", "t2", "t3"])
        publisher = XPublisher(client=client)

        tweets = ["Tweet A", "Tweet B", "Tweet C"]
        publisher.post_thread(tweets)

        first_call = client.create_tweet.call_args_list[0]
        assert "in_reply_to_tweet_id" not in first_call.kwargs

    def test_subsequent_tweets_reply_to_previous(self, monkeypatch):
        monkeypatch.setenv("X_USERNAME", "testuser")
        client = _mock_client(["t1", "t2", "t3"])
        publisher = XPublisher(client=client)

        publisher.post_thread(["A", "B", "C"])

        second_call = client.create_tweet.call_args_list[1]
        assert second_call.kwargs["in_reply_to_tweet_id"] == "t1"

        third_call = client.create_tweet.call_args_list[2]
        assert third_call.kwargs["in_reply_to_tweet_id"] == "t2"

    def test_returns_first_tweet_id_and_url(self, monkeypatch):
        monkeypatch.setenv("X_USERNAME", "finbot")
        client = _mock_client(["999"])
        publisher = XPublisher(client=client)

        first_id, url = publisher.post_thread(["Tek tweet"])
        assert first_id == "999"
        assert "finbot" in url
        assert "999" in url

    def test_tweets_truncated_to_280(self, monkeypatch):
        monkeypatch.setenv("X_USERNAME", "u")
        client = _mock_client(["1"])
        publisher = XPublisher(client=client)

        long_tweet = "X" * 300
        publisher.post_thread([long_tweet])

        sent_text = client.create_tweet.call_args.kwargs["text"]
        assert len(sent_text) <= 280


# ── Ana döngü ─────────────────────────────────────────────────────────────────

class TestXPublisherRun:
    def test_returns_empty_when_no_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        publisher = XPublisher(client=_mock_client())
        ids = publisher.run(date.today())
        assert ids == []

    def test_publishes_thread_and_updates_db(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("X_USERNAME", "bistbot")
        today = date.today().isoformat()
        cid = _seed_x_thread(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        client = _mock_client(["101", "102", "103"])
        publisher = XPublisher(client=client)
        ids = publisher.run(date.today())

        assert ids == [cid]
        row = tmp_db.fetchone("SELECT published_at, publish_url FROM content WHERE id=?", (cid,))
        assert row["publish_url"] is not None
        assert "bistbot" in row["publish_url"]
        assert row["published_at"] is not None

    def test_all_tweets_in_thread_sent(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("X_USERNAME", "u")
        today = date.today().isoformat()
        tweets = ["T1", "T2", "T3", "T4", "T5"]
        cid = _seed_x_thread(tmp_db, today, tweets=tweets)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        client = _mock_client([str(i) for i in range(5)])
        publisher = XPublisher(client=client)
        publisher.run(date.today())

        assert client.create_tweet.call_count == 5

    def test_skips_unapproved_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_x_thread(tmp_db, today, human_approved=0)

        publisher = XPublisher(client=_mock_client())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_compliance_failed(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_x_thread(tmp_db, today, compliance_passed=0, human_approved=1)

        publisher = XPublisher(client=_mock_client())
        ids = publisher.run(date.today())
        assert ids == []

    def test_skips_already_published(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = _seed_x_thread(tmp_db, today)
        tmp_db.execute(
            "UPDATE content SET human_approved=1, published_at='2026-06-12 08:00:00' WHERE id=?",
            (cid,),
        )

        publisher = XPublisher(client=_mock_client())
        ids = publisher.run(date.today())
        assert ids == []

    def test_malformed_body_skips_content(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        cid = db_insert_bad_content(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id=?", (cid,))

        publisher = XPublisher(client=_mock_client())
        ids = publisher.run(date.today())
        assert ids == []

    def test_api_error_skips_and_continues(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        monkeypatch.setenv("X_USERNAME", "u")
        today = date.today().isoformat()
        cid1 = _seed_x_thread(tmp_db, today)
        cid2 = _seed_x_thread(tmp_db, today)
        tmp_db.execute("UPDATE content SET human_approved=1 WHERE id IN (?,?)", (cid1, cid2))

        client = MagicMock()
        # İlk içerik hata, ikincisi OK
        client.create_tweet.side_effect = [
            RuntimeError("rate limit"),
            MagicMock(data={"id": "200"}),
            MagicMock(data={"id": "201"}),
            MagicMock(data={"id": "202"}),
        ]
        publisher = XPublisher(client=client)
        ids = publisher.run(date.today())

        # İlk hata fırlatır → atlanır; ikincisi geçer
        assert cid1 not in ids
        assert cid2 in ids


def db_insert_bad_content(db, date_str: str) -> int:
    return db.insert_content({
        "date": date_str,
        "platform": "x_thread",
        "title": "Bozuk içerik",
        "body": "bu JSON değil",
        "word_count": 3,
        "compliance_passed": 1,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })
