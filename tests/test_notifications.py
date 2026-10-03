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


# ── SEC-02: untrusted text is escaped in email HTML ─────────────────────────

def test_llm_summary_is_escaped_in_manager_digest():
    html = email_report.render_email_html(top_engineers=[], bottom_engineers=[], average_score=50.0,
                                          total_cost=10.0, ai_summary='<img src=x onerror="alert(1)">')

    assert "<img src=x" not in html
    assert "&lt;img src=x" in html


def test_engineer_name_is_escaped_in_developer_alert():
    html = email_report.render_developer_email(dict(DEV, name="<script>steal()</script>"))

    assert "<script>steal()" not in html
    assert "&lt;script&gt;steal()" in html


# ── PERF-02: one SMTP connection per dispatch; bounded Slack call ──────────

def _run_worker():
    from data.alert_worker import run_weekly_telemetry_check
    return run_weekly_telemetry_check()


def test_dispatch_logs_in_to_smtp_once(seeded_db, email_env, smtp):
    smtp_class, server = smtp

    summary = _run_worker()

    assert summary["developer_emails"]["sent"] == 10
    assert smtp_class.call_count == 1          # was one connection + login per email
    assert server.login.call_count == 1
    assert server.sendmail.call_count == 11    # 10 developers + manager digest
    server.quit.assert_called_once()


def test_dropped_connection_is_reopened_once_and_the_email_retried(seeded_db, email_env, smtp):
    smtp_class, server = smtp
    server.sendmail.side_effect = [None, email_report.smtplib.SMTPServerDisconnected("bye")] + [None] * 20

    summary = _run_worker()

    assert summary["developer_emails"] == {"sent": 10, "failed": 0, "skipped": 0}
    assert smtp_class.call_count == 2


def test_bad_credentials_fail_fast_instead_of_retrying_every_email(seeded_db, email_env, smtp):
    smtp_class, server = smtp
    server.login.side_effect = email_report.smtplib.SMTPAuthenticationError(535, b"bad credentials")

    summary = _run_worker()

    assert summary["developer_emails"]["failed"] == 10
    assert summary["manager_digest"] == "failed"
    assert server.login.call_count == 1        # not 11 failed logins against Gmail


def test_slack_request_has_a_timeout(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.test/T000/B000")
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = MagicMock(status=200)
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", urlopen)

    slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0)

    assert urlopen.call_args.kwargs.get("timeout") == slack_post.SLACK_TIMEOUT_SECONDS


# ── TEST-01a: Slack failure modes are reported, never raised ────────────────

@pytest.fixture
def slack_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.test/T000/B000")


def test_slack_non_200_response_is_a_failure(slack_webhook, monkeypatch):
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = MagicMock(status=204)
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", urlopen)

    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "failed"


def test_slack_http_error_reports_the_response_body(slack_webhook, monkeypatch, caplog):
    import io

    error = slack_post.urllib.error.HTTPError("https://hooks.example.test", 404, "Not Found", {},
                                              io.BytesIO(b"no_service"))
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", MagicMock(side_effect=error))

    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "failed"
    assert "no_service" in caplog.text  # Slack's reason, e.g. a revoked webhook


def test_slack_unexpected_error_does_not_crash_the_dispatch(slack_webhook, monkeypatch):
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", MagicMock(side_effect=ValueError("bad url")))

    assert slack_post.send_slack_summary([dict(DEV, rank=1)], 50.0, 10.0) == "failed"
