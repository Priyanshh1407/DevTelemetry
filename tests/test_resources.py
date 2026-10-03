"""ERR-02: connections are closed and file paths don't depend on the working directory."""
import sqlite3

import pytest

import core.db as db
from tests.conftest import engineer_id


@pytest.fixture
def tracked_connections(monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        # Endpoints run in a worker thread; sqlite checks the creating thread BEFORE whether the
        # connection is closed, so allow cross-thread use to make "closed" observable here.
        conn = real_connect(*args, **{**kwargs, "check_same_thread": False})
        opened.append(conn)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)
    return opened


def is_closed(conn):
    try:
        conn.execute("SELECT 1")
        return False
    except sqlite3.ProgrammingError as e:
        if "closed" in str(e):
            return True
        raise


@pytest.mark.parametrize("path", [
    "/api/leaderboard",
    "/api/trends",
    "/api/settings",
    f"/api/engineer/{engineer_id(3)}/details",
    "/api/engineer/nonexistent/details",          # error path (404) must close too
    f"/api/guide/{engineer_id(3)}",
    f"/api/runbook-tasks/critical/{engineer_id(3)}",
])
def test_endpoints_close_their_connections(client, seeded_db, tracked_connections, path):
    client.get(path)

    assert tracked_connections, "endpoint should have opened a connection"
    assert all(is_closed(c) for c in tracked_connections)


def test_settings_update_closes_its_connection(client, seeded_db, admin_headers, tracked_connections):
    client.post("/api/settings", json={"frequency": "Daily", "day": "Monday", "time": "08:00"},
                headers=admin_headers)

    assert all(is_closed(c) for c in tracked_connections)


def test_db_session_rolls_back_on_error(empty_db, query):
    with pytest.raises(RuntimeError):
        with db.db_session() as conn:
            conn.execute("UPDATE alert_settings SET frequency = 'Daily' WHERE id = 1")
            raise RuntimeError("boom")

    assert query("SELECT frequency FROM alert_settings")[0]["frequency"] == "Weekly"


def test_email_templates_render_from_any_working_directory(tmp_path, monkeypatch):
    from notifications import email_report

    monkeypatch.chdir(tmp_path)

    html = email_report.render_email_html(top_engineers=[], bottom_engineers=[], average_score=50.0,
                                          total_cost=10.0, ai_summary="memo")
    assert "memo" in html
