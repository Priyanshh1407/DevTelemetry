"""BUG-03: alert dispatch must report what actually happened."""
import smtplib

import pytest

import api.routes as routes
from tests.conftest import NUM_ENGINEERS


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
    return client.post("/api/trigger-alerts")


def test_all_sends_succeed_reports_counts(client, seeded_db, email_env, smtp_server):
    response = trigger(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    summary = body["summary"]
    assert summary["developer_emails"] == {"sent": NUM_ENGINEERS, "failed": 0, "skipped": 0}
    assert summary["manager_digest"] == "sent"
    assert summary["slack"] == "skipped"  # no webhook configured


def test_all_emails_failing_is_not_reported_as_success(client, seeded_db, email_env, smtp_server):
    smtp_server.sendmail.side_effect = smtplib.SMTPException("relay denied")

    response = trigger(client)

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["status"] == "failed"
    assert detail["summary"]["developer_emails"]["failed"] == NUM_ENGINEERS
    assert detail["summary"]["manager_digest"] == "failed"
    assert len(detail["summary"]["failed_recipients"]) == NUM_ENGINEERS


def test_partial_failure_is_reported(client, seeded_db, email_env, smtp_server):
    # First developer email fails, everything else succeeds.
    smtp_server.sendmail.side_effect = [smtplib.SMTPException("boom")] + [None] * 20

    detail = trigger(client).json()["detail"]

    assert detail["summary"]["developer_emails"] == {"sent": NUM_ENGINEERS - 1, "failed": 1, "skipped": 0}


def test_nothing_configured_is_reported_as_skipped(client, seeded_db):
    response = trigger(client)

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


def test_no_usage_data_returns_409(client, empty_db):
    assert trigger(client).status_code == 409


def test_unexpected_error_does_not_leak_internals(client, seeded_db, monkeypatch):
    def explode():
        raise RuntimeError("sqlite at C:/secret/path is locked")

    monkeypatch.setattr(routes, "run_weekly_telemetry_check", explode)

    response = trigger(client)

    assert response.status_code == 500
    assert "secret" not in response.text
