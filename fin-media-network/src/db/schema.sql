-- AI Financial Media Network — SQLite Schema
-- Tüm timestamplar UTC olarak saklanır

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ─── LAYER 1: Ham haberler ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_news (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash    TEXT NOT NULL UNIQUE,          -- sha256(canonicalized_url)
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    source_name TEXT NOT NULL,
    source_url  TEXT,
    published_at DATETIME,                     -- UTC
    fetched_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    feed_name   TEXT,                          -- hangi RSS feed'den geldi
    raw_json    TEXT,                          -- orijinal feedparser dict (JSON)
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    cluster_id  INTEGER REFERENCES clusters(id)
);

CREATE INDEX IF NOT EXISTS idx_raw_news_fetched ON raw_news(fetched_at);
CREATE INDEX IF NOT EXISTS idx_raw_news_cluster ON raw_news(cluster_id);
CREATE INDEX IF NOT EXISTS idx_raw_news_hash ON raw_news(url_hash);

-- ─── LAYER 2: Olay kümeleri ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clusters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    date            DATE NOT NULL,              -- pipeline tarihi (TR saatiyle gün)
    representative_title TEXT NOT NULL,         -- kümenin en iyi başlığı
    news_count      INTEGER NOT NULL DEFAULT 1,
    source_weight   REAL NOT NULL DEFAULT 0.0,  -- max kaynak ağırlığı küme içinde
    market_relevance REAL NOT NULL DEFAULT 0.0, -- keyword eşleşme skoru
    volatility_impact REAL NOT NULL DEFAULT 0.0,
    score           REAL NOT NULL DEFAULT 0.0,  -- bileşik skor (0-100)
    tier            INTEGER,                    -- 1, 2, veya NULL (arşiv)
    keywords        TEXT,                       -- JSON array
    tickers_mentioned TEXT                      -- JSON array
);

CREATE INDEX IF NOT EXISTS idx_clusters_date ON clusters(date);
CREATE INDEX IF NOT EXISTS idx_clusters_tier ON clusters(tier);
CREATE INDEX IF NOT EXISTS idx_clusters_score ON clusters(score);

-- ─── LAYER 2: Piyasa anlık görüntüleri ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    date        DATE NOT NULL,
    ticker      TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    change_pct  REAL,                           -- günlük değişim %
    source      TEXT NOT NULL,                  -- "yfinance" | "stooq" | "coingecko" | "fred" | "evds"
    extra_json  TEXT                            -- ek alanlar (JSON)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_unique ON market_snapshots(date, ticker, source);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON market_snapshots(date);

-- ─── LAYER 3: Sinyaller (Research Agent çıktısı) ──────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    date            DATE NOT NULL,
    cluster_id      INTEGER REFERENCES clusters(id),
    headline        TEXT NOT NULL,              -- 1 cümle özet
    what_happened   TEXT NOT NULL,
    why_it_matters  TEXT NOT NULL,
    bias            TEXT,                       -- "bullish" | "bearish" | "neutral"
    confidence      REAL,                       -- 0.0-1.0
    transmission_rule_ids TEXT,                 -- JSON array — hangi matris kuralları tetiklendi
    bist_impact_json TEXT,                      -- analyst_agent BIST analizi (JSON)
    rank            INTEGER                     -- günlük 1–8 sıralama
);

CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);

-- ─── LAYER 3: Üretilen içerikler ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    date            DATE NOT NULL,
    platform        TEXT NOT NULL,              -- "youtube" | "tiktok_1..4" | "x_brief" | "x_thread" | "x_closing"
    title           TEXT,
    body            TEXT NOT NULL,
    word_count      INTEGER,
    compliance_passed INTEGER NOT NULL DEFAULT 0,
    compliance_warnings TEXT,                   -- JSON array
    human_approved  INTEGER NOT NULL DEFAULT 0,
    approved_at     DATETIME,
    published_at    DATETIME,
    publish_url     TEXT,
    prompt_version_id INTEGER REFERENCES prompt_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_content_date ON content(date);
CREATE INDEX IF NOT EXISTS idx_content_platform ON content(platform);

-- ─── LAYER 6: Performans metrikleri ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    content_id      INTEGER REFERENCES content(id),
    platform        TEXT NOT NULL,
    views           INTEGER,
    likes           INTEGER,
    comments        INTEGER,
    shares          INTEGER,
    watch_time_sec  INTEGER,                    -- YouTube için
    retention_pct   REAL,                       -- YouTube için
    ctr             REAL,                       -- YouTube thumbnail CTR
    engagement_rate REAL,
    impressions     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_performance_content ON performance(content_id);

-- ─── LAYER 6: Prompt versiyonları (Feedback Agent yönetir) ───────────────────
CREATE TABLE IF NOT EXISTS prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    platform        TEXT NOT NULL,
    version         TEXT NOT NULL,              -- "v1.0", "v1.1" gibi
    prompt_text     TEXT NOT NULL,
    parameter_json  TEXT,                       -- A/B test parametreleri (JSON)
    is_active       INTEGER NOT NULL DEFAULT 1,
    performance_score REAL,                     -- feedback_agent atar
    notes           TEXT
);

-- ─── LLM maliyet logu ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at       DATETIME NOT NULL DEFAULT (datetime('now')),
    agent           TEXT NOT NULL,              -- "research" | "analyst" | "narrative" | "content" | "feedback"
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    total_tokens    INTEGER NOT NULL,
    cost_usd        REAL NOT NULL,
    duration_ms     INTEGER,
    success         INTEGER NOT NULL DEFAULT 1,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_date ON llm_calls(called_at);
