"""ML-03a: databases created before the token-field change are converted once, on startup."""
import sqlite3

import pytest

from core.db import db_session, init_db
from core.scorer import SCORING_VERSION, calculate_efficiency_score

OLD_SCHEMA = """
    CREATE TABLE engineers (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL);
    CREATE TABLE usage_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, date TEXT NOT NULL,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
        opus_pct REAL, sonnet_pct REAL, haiku_pct REAL, session_count INTEGER, compact_uses INTEGER,
        git_commits INTEGER, estimated_cost_usd REAL, efficiency_score REAL, UNIQUE(user_id, date));
    CREATE TABLE alert_settings (id INTEGER PRIMARY KEY CHECK (id = 1), frequency TEXT NOT NULL,
                                 day TEXT, time TEXT NOT NULL);
"""


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    """A database written by the pre-ML-03 code: input_tokens INCLUDED cache reads."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO engineers VALUES ('u1', 'Old Timer', 'old@example.com')")
    # 1,000,000 prompt tokens of which 800,000 were cache reads; 50,000 cache writes on top.
    conn.execute("""INSERT INTO usage_metrics (user_id, date, input_tokens, output_tokens, cache_read_tokens,
                    cache_write_tokens, opus_pct, sonnet_pct, haiku_pct, session_count, compact_uses, git_commits,
                    estimated_cost_usd, efficiency_score)
                    VALUES ('u1', '2026-01-01', 1000000, 20000, 800000, 50000, 0.2, 0.5, 0.3, 4, 2, 3, 3.21, 70.4)""")
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(path))
    return path


def row(query_sql="SELECT * FROM usage_metrics"):
    with db_session() as conn:
        return dict(conn.execute(query_sql).fetchone())


def test_old_rows_are_converted_to_anthropic_semantics(old_db):
    init_db()

    r = row()
    assert r["input_tokens"] == 200_000            # 1,000,000 total minus the 800,000 cache reads
    assert r["cache_read_tokens"] == 800_000       # unchanged
    assert r["estimated_cost_usd"] == 3.21         # cost was already computed on uncached input


def test_old_scores_are_recomputed_with_the_current_formula(old_db):
    init_db()

    r = row()
    with db_session() as conn:
        history = [dict(x) for x in conn.execute("SELECT * FROM usage_metrics ORDER BY date")]
    assert r["efficiency_score"] == calculate_efficiency_score(history[-1], history[:-1])
    assert r["efficiency_score"] != 70.4


def test_migration_runs_once(old_db):
    init_db()
    first = row()
    init_db()
    init_db()

    assert row() == first  # a second conversion would subtract the cache reads again


def test_markers_are_recorded(old_db):
    init_db()

    with db_session() as conn:
        meta = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
    assert meta == {"token_semantics": "anthropic", "scoring_version": str(SCORING_VERSION)}


def test_a_new_database_is_marked_without_touching_data(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "new.db"))

    init_db()

    with db_session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM usage_metrics").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM schema_meta WHERE key = 'token_semantics'").fetchone()[0] == "anthropic"


def test_a_scoring_formula_change_rescores_existing_rows(empty_db, monkeypatch):
    import core.db as db

    from tests.conftest import seed_db

    seed_db(num_days=2)
    with db_session() as conn:
        conn.execute("UPDATE usage_metrics SET efficiency_score = -1")
        conn.execute("UPDATE schema_meta SET value = '0' WHERE key = 'scoring_version'")

    db.init_db()

    with db_session() as conn:
        assert conn.execute("SELECT MIN(efficiency_score) FROM usage_metrics").fetchone()[0] >= 0
