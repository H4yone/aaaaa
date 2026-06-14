"""
SQLite wrapper — tüm DB erişimi buradan geçer.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_DEFAULT_DB_PATH = os.getenv("DB_PATH", "media_network.db")


class Database:
    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
        logger.info("DB initialized: %s", self.db_path)

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Generic helpers ──────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.get_conn() as conn:
            return conn.execute(sql, params)

    def executemany(self, sql: str, params_seq: list[tuple]) -> None:
        with self.get_conn() as conn:
            conn.executemany(sql, params_seq)

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.get_conn() as conn:
            return conn.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.get_conn() as conn:
            return conn.execute(sql, params).fetchone()

    # ── Table helpers ────────────────────────────────────────────────────────

    def insert_raw_news(self, rows: list[dict]) -> int:
        sql = """
            INSERT OR IGNORE INTO raw_news
                (url_hash, url, title, summary, source_name, source_url,
                 published_at, feed_name, raw_json)
            VALUES
                (:url_hash, :url, :title, :summary, :source_name, :source_url,
                 :published_at, :feed_name, :raw_json)
        """
        with self.get_conn() as conn:
            cursor = conn.executemany(sql, rows)
            return cursor.rowcount

    def insert_market_snapshot(self, row: dict) -> None:
        sql = """
            INSERT OR REPLACE INTO market_snapshots
                (date, ticker, open, high, low, close, volume, change_pct, source, extra_json)
            VALUES
                (:date, :ticker, :open, :high, :low, :close, :volume, :change_pct, :source, :extra_json)
        """
        with self.get_conn() as conn:
            conn.execute(sql, row)

    def insert_cluster(self, row: dict) -> int:
        sql = """
            INSERT INTO clusters
                (date, representative_title, news_count, source_weight,
                 market_relevance, volatility_impact, score, tier, keywords, tickers_mentioned)
            VALUES
                (:date, :representative_title, :news_count, :source_weight,
                 :market_relevance, :volatility_impact, :score, :tier, :keywords, :tickers_mentioned)
        """
        with self.get_conn() as conn:
            cursor = conn.execute(sql, row)
            return cursor.lastrowid

    def insert_signal(self, row: dict) -> int:
        sql = """
            INSERT INTO signals
                (date, cluster_id, headline, what_happened, why_it_matters,
                 bias, confidence, transmission_rule_ids, bist_impact_json, rank)
            VALUES
                (:date, :cluster_id, :headline, :what_happened, :why_it_matters,
                 :bias, :confidence, :transmission_rule_ids, :bist_impact_json, :rank)
        """
        with self.get_conn() as conn:
            cursor = conn.execute(sql, row)
            return cursor.lastrowid

    def insert_content(self, row: dict) -> int:
        sql = """
            INSERT INTO content
                (date, platform, title, body, word_count,
                 compliance_passed, compliance_warnings, prompt_version_id)
            VALUES
                (:date, :platform, :title, :body, :word_count,
                 :compliance_passed, :compliance_warnings, :prompt_version_id)
        """
        with self.get_conn() as conn:
            cursor = conn.execute(sql, row)
            return cursor.lastrowid

    def log_llm_call(self, row: dict) -> None:
        sql = """
            INSERT INTO llm_calls
                (agent, model, input_tokens, output_tokens, total_tokens,
                 cost_usd, duration_ms, success, error_message)
            VALUES
                (:agent, :model, :input_tokens, :output_tokens, :total_tokens,
                 :cost_usd, :duration_ms, :success, :error_message)
        """
        with self.get_conn() as conn:
            conn.execute(sql, row)

    def get_daily_llm_cost(self, date: str) -> float:
        row = self.fetchone(
            "SELECT SUM(cost_usd) as total FROM llm_calls WHERE date(called_at)=?",
            (date,),
        )
        return float(row["total"] or 0.0)

    def get_monthly_llm_cost(self, year_month: str) -> float:
        row = self.fetchone(
            "SELECT SUM(cost_usd) as total FROM llm_calls WHERE strftime('%Y-%m', called_at)=?",
            (year_month,),
        )
        return float(row["total"] or 0.0)

    def get_daily_llm_tokens(self, date: str) -> int:
        row = self.fetchone(
            "SELECT SUM(total_tokens) as total FROM llm_calls WHERE date(called_at)=?",
            (date,),
        )
        return int(row["total"] or 0)

    def get_monthly_llm_tokens(self, year_month: str) -> int:
        row = self.fetchone(
            "SELECT SUM(total_tokens) as total FROM llm_calls WHERE strftime('%Y-%m', called_at)=?",
            (year_month,),
        )
        return int(row["total"] or 0)


# Singleton — pipeline modülleri bunu import eder
_db: Database | None = None


def get_db(db_path: str | Path | None = None) -> Database:
    global _db
    if _db is None:
        _db = Database(db_path or _DEFAULT_DB_PATH)
    return _db


def reset_db(db_path: str | Path | None = None) -> Database:
    global _db
    _db = Database(db_path or _DEFAULT_DB_PATH)
    return _db


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if "--init" in sys.argv:
        db = get_db()
        db.init()
        print(f"Veritabanı oluşturuldu: {db.db_path.resolve()}")
    else:
        print("Kullanım: python -m src.db.database --init")
