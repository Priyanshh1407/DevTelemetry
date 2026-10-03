"""Notification senders, with SMTP and HTTP mocked at the boundary."""
from unittest.mock import MagicMock

import pytest

from notifications import email_report, slack_post

DEV = {"name": "Engineer 00", "email": "engineer00@example.com", "efficiency_score": 30.0,
       "estimated_cost_usd": 12.5, "user_id": "eng-00", "rank": 10, "total_devs": 10,
       "severity": "critical"}


@pytest.fixture
def smtp(monkeypatch):
    server = MagicMock()
    smtp_class = MagicMock(return_value=server)
    monkeypatch.setattr(email_report.smtplib, "SMTP", smtp_class)
    return smtp_class, server


@pytest.fixture
def email_env(monkeypatch):
    monkeypatch.setenv("EMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("EMAIL_RECIPIENT", "inbox@example.com")


# ── TEST-02: configuration is read at call time ─────────────────────────────

def test_email_credentials_are_read_at_call_time(email_env, smtp):
    smtp_class, server = smtp

    email_report.send_developer_alert(DEV)

    server.login.assert_called_once_with("sender@example.com", "app-password")
    assert server.sendmail.call_args.args[1] == "inbox@example.com"  # demo mode routes to the test inbox


def test_email_is_skipped_without_credentials(smtp):
    smtp_class, _ = smtp

    email_report.send_developer_alert(DEV)
    email_report.send_daily_report(top_engineers=[], bottom_engineers=[], average_score=50.0,
                                   total_cost=10.0, ai_summary="memo")

    smtp_class.assert_not_called()


def test_slack_webhook_is_read_at_call_time(monkeypatch):
    response = MagicMock(status=200)
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = response
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.test/T000/B000")

    slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0)

    urlopen.assert_called_once()
    assert urlopen.call_args.args[0].full_url == "https://hooks.example.test/T000/B000"


def test_slack_is_skipped_without_webhook(monkeypatch):
    urlopen = MagicMock()
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", urlopen)

    slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0)

    urlopen.assert_not_called()


def test_slack_dashboard_button_uses_frontend_url(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://dash.example.test")

    blocks = slack_post._build_slack_blocks([dict(DEV, rank=1)], 50.0, 10.0)["blocks"]

    button = next(b for b in blocks if b["type"] == "actions")["elements"][0]
    assert button["url"] == "https://dash.example.test"


# ── BUG-03: senders report what happened ────────────────────────────────────

def test_email_sender_returns_sent_failed_skipped(email_env, smtp, monkeypatch):
    _, server = smtp
    assert email_report.send_developer_alert(DEV) == "sent"

    server.sendmail.side_effect = email_report.smtplib.SMTPException("relay denied")
    assert email_report.send_developer_alert(DEV) == "failed"

    monkeypatch.delenv("EMAIL_PASSWORD")
    assert email_report.send_developer_alert(DEV) == "skipped"


def test_slack_sender_returns_sent_failed_skipped(monkeypatch):
    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "skipped"

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.test/T000/B000")
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = MagicMock(status=200)
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", urlopen)
    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "sent"

    urlopen.side_effect = slack_post.urllib.error.URLError("unreachable")
    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "failed"
