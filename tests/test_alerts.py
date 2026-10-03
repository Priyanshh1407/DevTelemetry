"""BUG-03 + PERF-02: dispatch runs in the background and reports what actually happened."""
import smtplib

import pytest

import api.routes as routes
from tests.conftest import ADMIN_TOKEN, NUM_ENGINEERS


@pytest.fixture(autouse=True)
def _admin(admin_token):
    """All dispatch tests act as the admin; auth itself is covered in test_security.py."""


@pytest.fixture
def email_env(monkeypatch):
    monkeypatch.setenv("EMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("EMAIL_RECIPIENT", "inbox@example.com")


@pytest.fixture
def smtp_server(monkeypatch):
    from unittest.mock import MagicMock

    from notifications import email_report

    server = MagicMock()
    monkeypatch.setattr(email_report.smtplib, "SMTP", MagicMock(return_value=server))
    return server


def trigger(client):
    return client.post("/api/trigger-alerts", headers={"X-Admin-Token": ADMIN_TOKEN})


def dispatch(client):
    """Starts a dispatch and returns the finished run.

    TestClient runs background tasks before returning, so the run is final when we read it."""
    response = trigger(client)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running"
    run = client.get(body["status_url"])
    assert run.status_code == 200
    return run.json()


def test_trigger_answers_immediately_with_a_run_to_poll(client, seeded_db):
    response = trigger(client)

    assert response.status_code == 202
    assert response.json()["status_url"] == f"/api/dispatch-runs/{response.json()['run_id']}"


def test_all_sends_succeed_reports_counts(client, seeded_db, email_env, smtp_server):
    run = dispatch(client)

    assert run["status"] == "success"
    assert run["summary"]["developer_emails"] == {"sent": NUM_ENGINEERS, "failed": 0, "skipped": 0}
    assert run["summary"]["manager_digest"] == "sent"
    assert run["summary"]["slack"] == "skipped"  # no webhook configured
    assert f"{NUM_ENGINEERS} sent" in run["message"]


def test_all_emails_failing_is_not_reported_as_success(client, seeded_db, email_env, smtp_server):
    smtp_server.sendmail.side_effect = smtplib.SMTPException("relay denied")

    run = dispatch(client)

    assert run["status"] == "failed"
    assert run["summary"]["developer_emails"]["failed"] == NUM_ENGINEERS
    assert run["summary"]["manager_digest"] == "failed"
    assert len(run["summary"]["failed_recipients"]) == NUM_ENGINEERS
    assert run["message"].startswith("Some notifications failed.")


def test_partial_failure_is_reported(client, seeded_db, email_env, smtp_server):
    # First developer email fails, everything else succeeds.
    smtp_server.sendmail.side_effect = [smtplib.SMTPException("boom")] + [None] * 20

    run = dispatch(client)

    assert run["status"] == "failed"
    assert run["summary"]["developer_emails"] == {"sent": NUM_ENGINEERS - 1, "failed": 1, "skipped": 0}


def test_nothing_configured_is_reported_as_skipped(client, seeded_db):
    run = dispatch(client)

    assert run["status"] == "skipped"
    assert run["message"].startswith("Nothing was sent")


def test_no_usage_data_is_rejected_before_starting_a_run(client, empty_db, query):
    assert trigger(client).status_code == 409
    assert query("SELECT COUNT(*) AS n FROM dispatch_runs")[0]["n"] == 0


def test_unexpected_error_is_recorded_without_leaking_internals(client, seeded_db, monkeypatch):
    def explode():
        raise RuntimeError("sqlite at C:/secret/path is locked")

    monkeypatch.setattr(routes, "run_weekly_telemetry_check", explode)

    run = dispatch(client)

    assert run["status"] == "error"
    assert "secret" not in str(run)


def test_unknown_run_is_404(client):
    assert client.get("/api/dispatch-runs/12345").status_code == 404


def test_startup_upgrades_a_database_created_before_dispatch_runs(tmp_path, monkeypatch):
    import sqlite3

    from fastapi.testclient import TestClient

    from api.main import app

    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(old_db)
    conn.executescript("""
        CREATE TABLE engineers (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL);
        CREATE TABLE usage_metrics (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, efficiency_score REAL);
        CREATE TABLE alert_settings (id INTEGER PRIMARY KEY CHECK (id = 1), frequency TEXT, day TEXT, time TEXT);
    """)
    conn.close()
    monkeypatch.setenv("DB_PATH", str(old_db))

    with TestClient(app) as client:  # the context manager runs the app's startup
        assert client.get("/api/dispatch-runs/1").status_code == 404  # table exists; just no such run


@pytest.mark.parametrize("status, expected", [
    ("running", "Sending alerts..."),
    ("no_data", "No usage data to report yet."),
    ("abandoned", "The dispatch was interrupted (server restart?) before it finished."),
])
def test_dispatch_run_messages_for_every_state(client, seeded_db, status, expected):
    from core.dispatch import finish_run, start_run

    run_id = start_run("manual")
    if status != "running":
        finish_run(run_id, status)

    assert client.get(f"/api/dispatch-runs/{run_id}").json()["message"] == expected
