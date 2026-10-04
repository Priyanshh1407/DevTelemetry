import logging
import sqlite3
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Resolve paths from this file's location so the app works from any working directory.
# DB_PATH can be overridden (e.g. tests point it at a temporary database).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "data", "schema.sql")


def get_db_path():
    """Returns the active database path, read at call time so it can be overridden."""
    return os.getenv("DB_PATH", os.path.join(PROJECT_ROOT, "data", "usage.db"))


def get_db_connection():
    """
    Creates and returns a database connection. The caller must close it;
    prefer db_session(), which does that.
    Sets row_factory so we can access columns by name (like a dictionary).
    """
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    """Connection for one unit of work: commits on success, rolls back on error, always closes.

    (sqlite3's own `with conn:` only commits/rolls back. It never closes the connection,
    so every request that used it leaked a file handle until garbage collection.)
    """
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS never alters an existing
# table, so databases created earlier get these via ALTER TABLE (additive and idempotent).
ADDED_COLUMNS = [
    ("alert_settings", "timezone", "TEXT NOT NULL DEFAULT 'UTC'"),
    ("usage_metrics", "cost_price_version", "TEXT"),  # price table used for estimated_cost_usd
]


def _add_missing_columns(conn):
    for table, column, definition in ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _set_meta(conn, key, value):
    conn.execute("INSERT INTO schema_meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))


def rescore(conn, user_ids=None):
    """Recomputes stored efficiency scores with the current formula, for the given engineers
    (default: everyone). Each day is scored with its trailing window, like at write time."""
    from core.scorer import score_history  # local import: core.scorer has no DB dependency

    if user_ids is None:
        user_ids = [r["user_id"] for r in conn.execute("SELECT DISTINCT user_id FROM usage_metrics")]
    for user_id in user_ids:
        days = [dict(r) for r in conn.execute(
            "SELECT * FROM usage_metrics WHERE user_id = ? ORDER BY date", (user_id,))]
        for day, score in zip(days, score_history(days), strict=True):
            conn.execute("UPDATE usage_metrics SET efficiency_score = ? WHERE id = ?", (score, day["id"]))


def _migrate_data(conn):
    """One-time data conversions, tracked in schema_meta so each runs exactly once.

    Runs inside init_db's transaction: either the whole migration applies or none of it.
    """
    from core.scorer import SCORING_VERSION

    meta = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())

    # ai_guides was created by the original schema but never written by any code; coaching
    # guides now live in coaching_guides. Drop it only if it is empty (never destroy data).
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ai_guides'").fetchone():
        if conn.execute("SELECT COUNT(*) FROM ai_guides").fetchone()[0] == 0:
            conn.execute("DROP TABLE ai_guides")

    if meta.get("token_semantics") != "anthropic":
        # Before ML-03a, input_tokens INCLUDED cache reads. Anthropic's usage object (and now this
        # schema) counts only uncached tokens there. Cost is unaffected: it already billed the
        # uncached part as input - cache_read, which is exactly the new input_tokens.
        conn.execute("UPDATE usage_metrics SET input_tokens = MAX(input_tokens - cache_read_tokens, 0)")
        _set_meta(conn, "token_semantics", "anthropic")
        meta["scoring_version"] = None  # the hit ratio changed, so scores must be recomputed

    if meta.get("scoring_version") != str(SCORING_VERSION):
        rescore(conn)
        _set_meta(conn, "scoring_version", SCORING_VERSION)


def init_db():
    """
    Initializes the database by running the schema.sql file.
    Only creates tables if they don't already exist.
    """
    # Ensure the data directory exists
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with open(SCHEMA_PATH, 'r') as f:
        schema_script = f.read()
    with db_session() as conn:
        # executescript allows us to run multiple SQL commands at once
        conn.executescript(schema_script)
        _add_missing_columns(conn)
        _migrate_data(conn)

    logger.info("Database initialized at %s", db_path)


if __name__ == "__main__":
    # Allows you to run this file directly to test the setup
    init_db()
