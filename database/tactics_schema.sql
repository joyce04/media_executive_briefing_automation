-- Tactics pipeline infrastructure
CREATE TABLE IF NOT EXISTS tactics_pipeline_runs (
    run_uuid                TEXT PRIMARY KEY,
    week_start              DATE NOT NULL,
    week_end                DATE NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'started',
    started_at              DATETIME NOT NULL DEFAULT (datetime('now')),
    completed_at            DATETIME,
    articles_collected      INTEGER DEFAULT 0,
    articles_analyzed       INTEGER DEFAULT 0,
    error_message           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tactics_runs_week ON tactics_pipeline_runs(week_start);

CREATE TABLE IF NOT EXISTS tactics_raw_articles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid                TEXT NOT NULL,
    source_id               TEXT NOT NULL,
    url                     TEXT NOT NULL,
    url_hash                TEXT NOT NULL UNIQUE,
    title                   TEXT NOT NULL,
    body_text               TEXT,
    summary_from_source     TEXT,
    published_at            DATETIME,
    collected_at            DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uuid) REFERENCES tactics_pipeline_runs(run_uuid)
);
CREATE INDEX IF NOT EXISTS idx_tactics_raw_run ON tactics_raw_articles(run_uuid);
CREATE INDEX IF NOT EXISTS idx_tactics_raw_published ON tactics_raw_articles(published_at);

CREATE TABLE IF NOT EXISTS tactics_deduplicated_articles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid                TEXT NOT NULL,
    canonical_article_id    INTEGER NOT NULL,
    dedup_cluster_id        TEXT NOT NULL,
    dedup_method            TEXT NOT NULL,
    confidence              REAL NOT NULL DEFAULT 1.0,
    duplicate_count         INTEGER NOT NULL DEFAULT 1,
    duplicate_ids           TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (run_uuid) REFERENCES tactics_pipeline_runs(run_uuid),
    FOREIGN KEY (canonical_article_id) REFERENCES tactics_raw_articles(id)
);
CREATE INDEX IF NOT EXISTS idx_tactics_dedup_run ON tactics_deduplicated_articles(run_uuid);

CREATE TABLE IF NOT EXISTS tactics_article_analyses (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid                    TEXT NOT NULL,
    deduplicated_article_id     INTEGER NOT NULL,
    raw_article_id              INTEGER NOT NULL,
    tactical_theme              TEXT,
    formations_discussed        TEXT DEFAULT '[]',
    concepts_mentioned          TEXT DEFAULT '[]',
    teams_referenced            TEXT DEFAULT '[]',
    coaches_referenced          TEXT DEFAULT '[]',
    leagues_referenced          TEXT DEFAULT '[]',
    difficulty_level            TEXT,
    summary_en                  TEXT,
    summary_ko                  TEXT,
    key_insight                 TEXT,
    model_used                  TEXT,
    prompt_tokens               INTEGER,
    completion_tokens           INTEGER,
    analyzed_at                 DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uuid) REFERENCES tactics_pipeline_runs(run_uuid),
    FOREIGN KEY (deduplicated_article_id) REFERENCES tactics_deduplicated_articles(id),
    FOREIGN KEY (raw_article_id) REFERENCES tactics_raw_articles(id)
);
CREATE INDEX IF NOT EXISTS idx_tactics_analyses_run ON tactics_article_analyses(run_uuid);

CREATE TABLE IF NOT EXISTS tactics_weekly_synthesis (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid                TEXT NOT NULL,
    week_start              DATE NOT NULL UNIQUE,
    week_end                DATE NOT NULL,
    novel_tactics           TEXT DEFAULT '[]',
    executive_summary_ko    TEXT DEFAULT '[]',
    top_themes_ko           TEXT DEFAULT '[]',
    formation_trends_ko     TEXT DEFAULT '[]',
    set_piece_insights_ko   TEXT DEFAULT '[]',
    articles_synthesized    INTEGER NOT NULL DEFAULT 0,
    model_used              TEXT,
    synthesized_at          DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uuid) REFERENCES tactics_pipeline_runs(run_uuid)
);
