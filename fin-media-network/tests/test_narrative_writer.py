"""
NarrativeWriter testleri — LLM, ComplianceChecker ve DB mocklıdır.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.content.compliance_checker import ComplianceChecker, ComplianceResult
from src.db.database import reset_db
from src.intelligence.llm_client import BudgetExceeded, LLMResponse
from src.content.narrative_writer import NarrativeWriter


@pytest.fixture()
def tmp_db(tmp_path):
    db = reset_db(tmp_path / "test.db")
    db.init()
    return db


def _make_resp(text: str) -> LLMResponse:
    return LLMResponse(
        content=text,
        input_tokens=500, output_tokens=200,
        total_tokens=700, cost_usd=0.001, duration_ms=800,
    )


def _passing_compliance(body: str) -> ComplianceResult:
    return ComplianceResult(passed=True, warnings=[], body=body)


def _failing_compliance(body: str) -> ComplianceResult:
    return ComplianceResult(passed=False, warnings=["YASAK: almalısınız"], body=body)


def _seed_signal(db, date_str: str) -> int:
    cid = db.insert_cluster({
        "date": date_str,
        "representative_title": "Fed hawkish kararı",
        "news_count": 3,
        "source_weight": 0.9,
        "market_relevance": 0.8,
        "volatility_impact": 0.7,
        "score": 80.0,
        "tier": 1,
        "keywords": json.dumps(["Fed", "hawkish"]),
        "tickers_mentioned": json.dumps([]),
    })
    return db.insert_signal({
        "date": date_str,
        "cluster_id": cid,
        "headline": "Fed faizi artırdı, BIST baskı altında",
        "what_happened": "Fed 25 baz puan faiz artırdı.",
        "why_it_matters": "EM'den fon çıkışı BIST'i olumsuz etkiler.",
        "bias": "bearish",
        "confidence": 0.80,
        "transmission_rule_ids": json.dumps(["fed_hawkish"]),
        "bist_impact_json": json.dumps({"overall": "negatif", "sectors": []}),
        "rank": 1,
    })


def _seed_brief(db, date_str: str, headline: str) -> int:
    return db.insert_content({
        "date": date_str,
        "platform": "analyst_brief",
        "title": headline,
        "body": json.dumps({
            "scenarios": {
                "bull": {"probability": 0.2, "description": "İyimser senaryo."},
                "base": {"probability": 0.6, "description": "Baz senaryo."},
                "bear": {"probability": 0.2, "description": "Kötümser senaryo."},
            }
        }),
        "word_count": None,
        "compliance_passed": 1,
        "compliance_warnings": json.dumps([]),
        "prompt_version_id": None,
    })


# ── Tam çalışma döngüsü ───────────────────────────────────────────────────────

class TestNarrativeWriterRun:
    def test_creates_youtube_tiktok_xthread(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        tiktok_json = json.dumps({
            "tiktok_1": "Script 1 metni buraya.",
            "tiktok_2": "Script 2 metni buraya.",
            "tiktok_3": "Script 3 metni buraya.",
            "tiktok_4": "Script 4 metni buraya.",
        })
        x_json = json.dumps({"tweets": [
            "Tweet 1: Fed faizi artırdı.",
            "Tweet 2: BIST nasıl etkilenir?",
            "Bu içerik yatırım tavsiyesi değildir.",
        ]})

        llm = MagicMock()
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            _make_resp(tiktok_json),
            _make_resp(x_json),
        ]
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = _passing_compliance

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        content_ids = writer.run(date.today())

        # 1 youtube + 4 tiktok + 1 x_thread = 6
        assert len(content_ids) == 6

    def test_returns_empty_when_no_signal(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        llm = MagicMock()
        writer = NarrativeWriter(llm_client=llm, compliance_checker=MagicMock())
        content_ids = writer.run(date.today())

        assert content_ids == []
        llm.call.assert_not_called()

    def test_compliance_failure_excludes_platform(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        tiktok_json = json.dumps({
            "tiktok_1": "t1", "tiktok_2": "t2",
            "tiktok_3": "t3", "tiktok_4": "t4",
        })
        x_json = json.dumps({"tweets": ["t", "Bu içerik yatırım tavsiyesi değildir."]})

        llm = MagicMock()
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            _make_resp(tiktok_json),
            _make_resp(x_json),
        ]
        # YouTube compliance başarısız, diğerleri geçiyor
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = (
            lambda body: _failing_compliance(body)
            if "YouTube" in body
            else _passing_compliance(body)
        )

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        content_ids = writer.run(date.today())

        # youtube yok → 4 tiktok + 1 x_thread = 5
        assert len(content_ids) == 5

    def test_budget_exceeded_stops_after_youtube(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        llm = MagicMock()
        # YouTube OK, TikTok'ta bütçe aşılıyor
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            BudgetExceeded("günlük limit"),
        ]
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = _passing_compliance

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        content_ids = writer.run(date.today())

        # Sadece YouTube kaydedildi
        assert len(content_ids) == 1
        row = tmp_db.fetchone("SELECT platform FROM content WHERE id=?", (content_ids[0],))
        assert row["platform"] == "youtube"

    def test_uses_analyst_brief_when_available(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)
        _seed_brief(tmp_db, today, "Fed faizi artırdı, BIST baskı altında")

        tiktok_json = json.dumps({
            "tiktok_1": "t1", "tiktok_2": "t2",
            "tiktok_3": "t3", "tiktok_4": "t4",
        })
        x_json = json.dumps({"tweets": ["t", "Bu içerik yatırım tavsiyesi değildir."]})

        llm = MagicMock()
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            _make_resp(tiktok_json),
            _make_resp(x_json),
        ]
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = _passing_compliance

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        writer.run(date.today())

        # YouTube çağrısı yapıldı ve senaryo bilgisi prompt'a girdi
        yt_call_kwargs = llm.call.call_args_list[0]
        prompt_content = yt_call_kwargs[1]["messages"][0]["content"]
        assert "BULL" in prompt_content or "BASE" in prompt_content

    def test_x_thread_disclaimer_appended_when_missing(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        tiktok_json = json.dumps({
            "tiktok_1": "t1", "tiktok_2": "t2",
            "tiktok_3": "t3", "tiktok_4": "t4",
        })
        # Disclaimer içermeyen tweetler
        x_json = json.dumps({"tweets": ["Tweet 1", "Tweet 2", "Tweet 3"]})

        llm = MagicMock()
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            _make_resp(tiktok_json),
            _make_resp(x_json),
        ]
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = _passing_compliance

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        content_ids = writer.run(date.today())

        x_row = tmp_db.fetchone(
            "SELECT body FROM content WHERE platform='x_thread'"
        )
        tweets = json.loads(x_row["body"])["tweets"]
        assert any("yatırım tavsiyesi" in t.lower() for t in tweets)

    def test_x_thread_tweet_truncated_to_280(self, tmp_db, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_db.db_path))
        today = date.today().isoformat()
        _seed_signal(tmp_db, today)

        long_tweet = "A" * 300
        tiktok_json = json.dumps({
            "tiktok_1": "t1", "tiktok_2": "t2",
            "tiktok_3": "t3", "tiktok_4": "t4",
        })
        x_json = json.dumps({
            "tweets": [long_tweet, "Bu içerik yatırım tavsiyesi değildir."]
        })

        llm = MagicMock()
        llm.call.side_effect = [
            _make_resp("YouTube metni bu içerik yatırım tavsiyesi değildir."),
            _make_resp(tiktok_json),
            _make_resp(x_json),
        ]
        checker = MagicMock(spec=ComplianceChecker)
        checker.check.side_effect = _passing_compliance

        writer = NarrativeWriter(llm_client=llm, compliance_checker=checker)
        writer.run(date.today())

        x_row = tmp_db.fetchone("SELECT body FROM content WHERE platform='x_thread'")
        tweets = json.loads(x_row["body"])["tweets"]
        assert all(len(t) <= 280 for t in tweets)
