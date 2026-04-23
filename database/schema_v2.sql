-- ============================================================
-- Media Intelligence Platform — Multi-Tenant Schema v2
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- Organization management
-- ============================================================

CREATE TABLE IF NOT EXISTS organizations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    name_short       TEXT NOT NULL,
    primary_color    TEXT NOT NULL DEFAULT '#1a56db',
    secondary_color  TEXT NOT NULL DEFAULT '#1e429f',
    logo_url         TEXT,
    language_primary TEXT NOT NULL DEFAULT 'en',
    timezone         TEXT NOT NULL DEFAULT 'UTC',
    schedule_cron    TEXT NOT NULL DEFAULT '0 7 * * *',
    model_tier       TEXT NOT NULL DEFAULT 'starter',  -- 'starter'|'pro'|'enterprise'
    is_active        BOOLEAN NOT NULL DEFAULT 1,
    created_at       DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at       DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS org_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'rss',   -- 'rss'|'google_news'|'api'
    url         TEXT NOT NULL,
    language    TEXT NOT NULL DEFAULT 'en',
    priority    TEXT NOT NULL DEFAULT 'medium', -- 'high'|'medium'|'low'
    is_active   BOOLEAN NOT NULL DEFAULT 1,
    UNIQUE(org_id, source_id)
);

CREATE TABLE IF NOT EXISTS org_entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id        INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_type   TEXT NOT NULL,  -- 'player'|'tournament'|'keyword_core'|'person'|'team'
    name_primary  TEXT NOT NULL,
    name_alt      TEXT,
    priority      INTEGER NOT NULL DEFAULT 2,  -- 1=high, 2=medium, 3=low
    attributes    TEXT NOT NULL DEFAULT '{}',  -- JSON: watch_reason, start_date, end_date, etc.
    is_active     BOOLEAN NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_org_entities_org ON org_entities(org_id, entity_type);

CREATE TABLE IF NOT EXISTS org_prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    prompt_key  TEXT NOT NULL,  -- 'keyword_generation'|'analysis'|'synthesis'|'deduplication'
    system_msg  TEXT NOT NULL,
    UNIQUE(org_id, prompt_key)
);

CREATE TABLE IF NOT EXISTS org_recipients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id    INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role      TEXT NOT NULL DEFAULT 'to',  -- 'to'|'cc'|'bcc'
    name      TEXT NOT NULL DEFAULT '',
    email     TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_org_recipients_org ON org_recipients(org_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id       INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key_hash     TEXT NOT NULL UNIQUE,  -- SHA-256 of raw key
    label        TEXT NOT NULL DEFAULT 'default',
    created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    last_used_at DATETIME,
    is_active    BOOLEAN NOT NULL DEFAULT 1
);

-- ============================================================
-- Users, auth, billing
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT,           -- NULL for Google-only accounts
    google_sub    TEXT UNIQUE,    -- Google OAuth subject ID
    name          TEXT NOT NULL DEFAULT '',
    avatar_url    TEXT,
    is_admin      BOOLEAN NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT 1,
    created_at    DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_orgs (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role    TEXT NOT NULL DEFAULT 'member',  -- 'owner'|'admin'|'member'
    PRIMARY KEY (user_id, org_id)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS plans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,   -- 'starter'|'pro'|'enterprise'
    max_recipients    INTEGER NOT NULL DEFAULT 5,
    max_orgs          INTEGER NOT NULL DEFAULT 1,
    model_tier        TEXT NOT NULL DEFAULT 'starter',
    stripe_price_id   TEXT,
    price_usd_monthly REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id                 INTEGER NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    plan_id                INTEGER NOT NULL REFERENCES plans(id),
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT UNIQUE,
    status                 TEXT NOT NULL DEFAULT 'trialing',  -- 'trialing'|'active'|'past_due'|'canceled'
    trial_ends_at          DATETIME,
    current_period_end     DATETIME,
    created_at             DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at             DATETIME NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Pipeline tables (multi-tenant: org_id on all)
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id                INTEGER NOT NULL REFERENCES organizations(id),
    run_date              DATE NOT NULL,
    run_uuid              TEXT NOT NULL UNIQUE,
    status                TEXT NOT NULL DEFAULT 'started',
    started_at            DATETIME NOT NULL DEFAULT (datetime('now')),
    completed_at          DATETIME,
    articles_collected    INTEGER DEFAULT 0,
    articles_deduplicated INTEGER DEFAULT 0,
    articles_analyzed     INTEGER DEFAULT 0,
    total_llm_calls       INTEGER DEFAULT 0,
    estimated_cost_usd    REAL DEFAULT 0.0,
    error_message         TEXT,
    UNIQUE(org_id, run_date)
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_org ON pipeline_runs(org_id, run_date);

CREATE TABLE IF NOT EXISTS raw_articles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id              INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid            TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    source_language     TEXT NOT NULL,
    url                 TEXT NOT NULL,
    url_hash            TEXT NOT NULL,
    title               TEXT NOT NULL,
    body_text           TEXT,
    summary_from_source TEXT,
    published_at        DATETIME,
    collected_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    fetch_status        TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(org_id, url_hash)
);
CREATE INDEX IF NOT EXISTS idx_raw_run ON raw_articles(run_uuid);
CREATE INDEX IF NOT EXISTS idx_raw_org ON raw_articles(org_id);
CREATE INDEX IF NOT EXISTS idx_raw_published ON raw_articles(published_at);

CREATE TABLE IF NOT EXISTS deduplicated_articles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id               INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid             TEXT NOT NULL,
    canonical_article_id INTEGER NOT NULL,
    dedup_cluster_id     TEXT NOT NULL,
    dedup_method         TEXT NOT NULL,
    confidence           REAL NOT NULL DEFAULT 1.0,
    duplicate_count      INTEGER NOT NULL DEFAULT 1,
    duplicate_ids        TEXT NOT NULL DEFAULT '[]',
    novelty_status       TEXT NOT NULL DEFAULT 'new',
    story_cluster_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dedup_run ON deduplicated_articles(run_uuid);
CREATE INDEX IF NOT EXISTS idx_dedup_org ON deduplicated_articles(org_id);

CREATE TABLE IF NOT EXISTS article_analyses (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id                  INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid                TEXT NOT NULL,
    deduplicated_article_id INTEGER NOT NULL,
    raw_article_id          INTEGER NOT NULL,
    sentiment               TEXT NOT NULL,
    sentiment_score         REAL NOT NULL,
    sentiment_rationale     TEXT,
    primary_topic           TEXT NOT NULL,
    secondary_topics        TEXT DEFAULT '[]',
    players_mentioned       TEXT DEFAULT '[]',
    clubs_mentioned         TEXT DEFAULT '[]',
    officials_mentioned     TEXT DEFAULT '[]',
    venues_mentioned        TEXT DEFAULT '[]',
    relevance_score         INTEGER NOT NULL,  -- renamed from kfa_relevance_score
    risk_flag               TEXT NOT NULL DEFAULT 'neutral',
    risk_rationale          TEXT,
    summary_primary         TEXT NOT NULL,  -- primary language summary
    summary_secondary       TEXT NOT NULL,  -- secondary language summary
    key_quote               TEXT,
    model_used              TEXT NOT NULL,
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    analyzed_at             DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analyses_run ON article_analyses(run_uuid);
CREATE INDEX IF NOT EXISTS idx_analyses_org ON article_analyses(org_id);
CREATE INDEX IF NOT EXISTS idx_analyses_risk ON article_analyses(risk_flag);

CREATE TABLE IF NOT EXISTS daily_synthesis (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id               INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid             TEXT NOT NULL,
    run_date             DATE NOT NULL,
    trending_narratives  TEXT NOT NULL DEFAULT '[]',
    crisis_alerts        TEXT NOT NULL DEFAULT '[]',
    pr_opportunities     TEXT NOT NULL DEFAULT '[]',
    competitive_intel    TEXT NOT NULL DEFAULT '[]',
    sentiment_today      REAL NOT NULL,
    sentiment_7day_avg   REAL,
    sentiment_trend      TEXT,
    recommended_actions  TEXT NOT NULL DEFAULT '[]',
    executive_summary    TEXT NOT NULL,  -- primary language
    executive_summary_en TEXT NOT NULL,  -- english fallback
    articles_synthesized INTEGER NOT NULL,
    model_used           TEXT NOT NULL,
    synthesized_at       DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE(org_id, run_date)
);
CREATE INDEX IF NOT EXISTS idx_synthesis_org ON daily_synthesis(org_id, run_date);

CREATE TABLE IF NOT EXISTS generated_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id          INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid        TEXT NOT NULL,
    run_date        DATE NOT NULL,
    report_format   TEXT NOT NULL,
    file_path       TEXT,
    file_size_bytes INTEGER,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    delivery_target TEXT,
    delivered_at    DATETIME,
    error_message   TEXT,
    generated_at    DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reports_org ON generated_reports(org_id, run_date);

CREATE TABLE IF NOT EXISTS daily_sentiment_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id            INTEGER NOT NULL REFERENCES organizations(id),
    run_date          DATE NOT NULL,
    total_articles    INTEGER NOT NULL,
    positive_count    INTEGER NOT NULL,
    neutral_count     INTEGER NOT NULL,
    negative_count    INTEGER NOT NULL,
    crisis_count      INTEGER NOT NULL,
    avg_sentiment_score REAL NOT NULL,
    top_topics        TEXT NOT NULL DEFAULT '[]',
    UNIQUE(org_id, run_date)
);
CREATE INDEX IF NOT EXISTS idx_sentiment_org ON daily_sentiment_history(org_id, run_date);

CREATE TABLE IF NOT EXISTS story_continuity (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id                     INTEGER NOT NULL REFERENCES organizations(id),
    story_cluster_id           TEXT NOT NULL,
    first_seen_date            DATE NOT NULL,
    last_seen_date             DATE NOT NULL,
    canonical_title            TEXT NOT NULL,
    days_active                INTEGER NOT NULL DEFAULT 1,
    status                     TEXT NOT NULL DEFAULT 'new',
    resolution_date            DATE,
    representative_article_ids TEXT NOT NULL DEFAULT '[]',
    latest_run_uuid            TEXT NOT NULL,
    UNIQUE(org_id, story_cluster_id)
);
CREATE INDEX IF NOT EXISTS idx_continuity_org ON story_continuity(org_id, last_seen_date);
CREATE INDEX IF NOT EXISTS idx_continuity_status ON story_continuity(status);

CREATE TABLE IF NOT EXISTS search_keyword_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id        INTEGER NOT NULL REFERENCES organizations(id),
    run_uuid      TEXT NOT NULL,
    run_date      DATE NOT NULL,
    keyword_query TEXT NOT NULL,
    language      TEXT NOT NULL,
    rationale     TEXT,
    source_type   TEXT NOT NULL,
    articles_found INTEGER DEFAULT 0,
    generated_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_keywords_org ON search_keyword_log(org_id, run_date);

-- ============================================================
-- Seed data: default plans
-- ============================================================

INSERT OR IGNORE INTO plans (name, max_recipients, max_orgs, model_tier, stripe_price_id, price_usd_monthly)
VALUES
    ('starter',    5,   1,  'starter',    NULL, 0.0),
    ('pro',        20,  3,  'pro',        NULL, 49.0),
    ('enterprise', 100, 10, 'enterprise', NULL, 199.0);
