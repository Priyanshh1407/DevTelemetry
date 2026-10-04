-- Table to store the developer profiles
CREATE TABLE IF NOT EXISTS engineers (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL
);

-- Table to store the daily token and usage metrics
CREATE TABLE IF NOT EXISTS usage_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    opus_pct REAL,
    sonnet_pct REAL,
    haiku_pct REAL,
    session_count INTEGER,
    compact_uses INTEGER,
    git_commits INTEGER,
    estimated_cost_usd REAL,
    cost_price_version TEXT, -- price table (core/pricing.py) the cost was computed with
    efficiency_score REAL, -- New: Store the calculated score
    FOREIGN KEY (user_id) REFERENCES engineers(user_id),
    UNIQUE(user_id, date)
);

-- Successful AI coaching guides (UPG-01), reused until the data, prompt or model changes.
-- Fallback (rule-based) guides are never stored, so an outage is never cached.
CREATE TABLE IF NOT EXISTS coaching_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    metrics_date TEXT NOT NULL,      -- the latest usage day the guide was generated from
    severity TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    source TEXT NOT NULL,            -- ai | ai_repaired
    guide_json TEXT NOT NULL,
    created_at TEXT NOT NULL,        -- UTC ISO-8601
    UNIQUE(user_id, metrics_date, severity, prompt_version, model)
);

-- One row per AI request handled (UPG-04): cache hits, model answers and fallbacks,
-- with the tokens, latency and cost of the model calls it took.
CREATE TABLE IF NOT EXISTS ai_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,        -- UTC ISO-8601
    purpose TEXT NOT NULL,           -- guide | team_report
    user_id TEXT,
    outcome TEXT NOT NULL,           -- cache_hit | ai | ai_repaired | invalid_output | rate_limited | unavailable
    model TEXT,
    prompt_version TEXT,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,  -- includes thinking tokens
    latency_ms INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ai_requests_created_at ON ai_requests(created_at);

-- Table to store the manager's alert scheduling preferences
CREATE TABLE IF NOT EXISTS alert_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Ensures only one settings row exists
    frequency TEXT NOT NULL,
    day TEXT,
    time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC'  -- IANA name; schedule times are wall-clock in this zone
);

-- Insert default settings if the table is empty
INSERT OR IGNORE INTO alert_settings (id, frequency, day, time) VALUES (1, 'Weekly', 'Friday', '17:00');

-- Data-format markers used by init_db() migrations (core/db.py), e.g. token_semantics, scoring_version.
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per alert dispatch (manual or scheduled). Replaces in-process locks so the
-- guarantees hold across restarts and processes.
CREATE TABLE IF NOT EXISTS dispatch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'schedule')),
    slot TEXT UNIQUE,               -- scheduled time slot (UTC ISO); NULL for manual runs. At most one run per slot.
    status TEXT NOT NULL,           -- running | success | failed | skipped | no_data | error | abandoned
    started_at TEXT NOT NULL,       -- UTC ISO-8601
    finished_at TEXT,
    summary_json TEXT
);

-- Single flight: the database itself rejects a second concurrent 'running' row.
CREATE UNIQUE INDEX IF NOT EXISTS one_running_dispatch ON dispatch_runs(status) WHERE status = 'running';
