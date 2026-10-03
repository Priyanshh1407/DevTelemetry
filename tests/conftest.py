import os
import socket
import sqlite3
from unittest.mock import MagicMock

import pytest

from core.db import init_db
from core.scorer import calculate_efficiency_score

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(PROJECT_ROOT, "data", "usage.db")

NUM_ENGINEERS = 10
LATEST_DATE = "2026-01-03"


# ── Safety guards ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def real_db_untouched():
    """Fails the run if any test modified the developer's real database."""
    before = os.path.getmtime(REAL_DB) if os.path.exists(REAL_DB) else None
    yield
    after = os.path.getmtime(REAL_DB) if os.path.exists(REAL_DB) else None
    assert before == after, "Tests modified data/usage.db; they must use the tmp DB fixture"


_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise RuntimeError(f"Network access blocked in tests (attempted {address})")
    return _real_connect(self, address)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Blocks outbound connections. Loopback stays allowed (asyncio uses it internally on Windows)."""
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


NOTIFICATION_ENV = ("EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECIPIENT", "SLACK_WEBHOOK_URL",
                    "PRODUCTION_MODE", "FRONTEND_URL")


@pytest.fixture(autouse=True)
def no_real_notification_credentials(monkeypatch):
    """Importing the app runs load_dotenv(), which may put real SMTP/Slack credentials in
    os.environ. Remove them so a test can only send through config it set up itself."""
    for name in NOTIFICATION_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def mock_gemini(monkeypatch):
    """Replaces the Gemini client with a mock that returns a fixed numbered list.

    The real key (possibly loaded from .env) is removed, so any path that bypasses
    the mock fails with AIUnavailableError instead of calling the real API."""
    import ai.guide_generator as gg

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = MagicMock()
    client.models.generate_content.return_value.text = "1. Mock tip one\n2. Mock tip two"
    monkeypatch.setattr(gg, "_client", client)
    return client


@pytest.fixture(autouse=True)
def clear_runbook_cache():
    """api.routes keeps a module-level cache; reset it so tests don't leak into each other."""
    import api.routes as routes

    routes.ai_task_cache.clear()
    yield
    routes.ai_task_cache.clear()


# ── Test database ───────────────────────────────────────────────────────────

def engineer_id(i):
    return f"eng-{i:02d}"


def make_metrics(i, day_index):
    """Deterministic metrics. Cache ratio and /compact rate both rise with i, so the
    score is strictly increasing in i: on any day rank 1 is eng-09 and rank 10 is eng-00."""
    input_tokens = 100_000
    sessions = 10
    return {
        "input_tokens": input_tokens,
        "output_tokens": 20_000 + 1_000 * i,
        "cache_read_tokens": 5_000 * (i + 1) + 100 * day_index,
        "cache_write_tokens": 10_000,
        "model_mix": {"opus_pct": 0.3, "sonnet_pct": 0.5, "haiku_pct": 0.2},
        "session_count": sessions,
        "compact_uses": i,
        "git_commits": i,
        "estimated_cost_usd": round(10.0 + i + day_index * 0.5, 2),
    }


def seed_db(num_days, start_date="2026-01-01"):
    """Inserts NUM_ENGINEERS engineers with num_days consecutive days of metrics."""
    from datetime import date, timedelta

    from core.db import get_db_connection

    start = date.fromisoformat(start_date)
    conn = get_db_connection()
    try:
        for i in range(NUM_ENGINEERS):
            conn.execute(
                "INSERT INTO engineers (user_id, name, email) VALUES (?, ?, ?)",
                (engineer_id(i), f"Engineer {i:02d}", f"engineer{i:02d}@example.com"),
            )
            for d in range(num_days):
                m = make_metrics(i, d)
                mix = m["model_mix"]
                conn.execute(
                    """INSERT INTO usage_metrics
                       (user_id, date, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                        opus_pct, sonnet_pct, haiku_pct, session_count, compact_uses, git_commits,
                        estimated_cost_usd, efficiency_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        engineer_id(i), (start + timedelta(days=d)).isoformat(),
                        m["input_tokens"], m["output_tokens"], m["cache_read_tokens"], m["cache_write_tokens"],
                        mix["opus_pct"], mix["sonnet_pct"], mix["haiku_pct"],
                        m["session_count"], m["compact_uses"], m["git_commits"],
                        m["estimated_cost_usd"], calculate_efficiency_score(m),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """A fresh database with the schema (and its default settings row) but no usage data."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db()
    return db_path


@pytest.fixture
def seeded_db(empty_db):
    """10 engineers x 3 days (2026-01-01 .. 2026-01-03)."""
    seed_db(num_days=3)
    return empty_db


@pytest.fixture
def query(empty_db):
    """Runs a read query against the test DB and returns rows as dicts."""
    def _query(sql, params=()):
        conn = sqlite3.connect(empty_db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    return _query


@pytest.fixture
def client(empty_db):
    """API test client. Depends on empty_db so it can never fall through to the real database."""
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)
