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
    efficiency_score REAL, -- New: Store the calculated score
    FOREIGN KEY (user_id) REFERENCES engineers(user_id),
    UNIQUE(user_id, date)
);

-- Table to store the AI-generated coaching guides
CREATE TABLE IF NOT EXISTS ai_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    guide_text TEXT NOT NULL,
    severity TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES engineers(user_id),
    UNIQUE(user_id, date)
);

-- Table to store the manager's alert scheduling preferences
CREATE TABLE IF NOT EXISTS alert_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Ensures only one settings row exists
    frequency TEXT NOT NULL,
    day TEXT,
    time TEXT NOT NULL
);

-- Insert default settings if the table is empty
INSERT OR IGNORE INTO alert_settings (id, frequency, day, time) VALUES (1, 'Weekly', 'Friday', '17:00');

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
