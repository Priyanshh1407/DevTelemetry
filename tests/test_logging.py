"""Hygiene: server code logs instead of printing.

Found during Phase 2/4 test runs: the alert worker printed emoji with print(). On a console
or redirected output using a legacy encoding (e.g. Windows cp1252) that raised
UnicodeEncodeError inside the dispatch, and the run ended as 'error' with no emails sent.
Logging handlers report encoding problems and carry on instead of raising into the caller.
"""
import io
import logging
import sys

from data.alert_worker import overall_status, run_weekly_telemetry_check


def test_dispatch_survives_an_output_stream_that_cannot_encode_emoji(seeded_db, monkeypatch):
    cp1252_console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp1252_console)
    monkeypatch.setattr(sys, "stderr", cp1252_console)

    summary = run_weekly_telemetry_check()

    assert overall_status(summary) == "skipped"  # nothing configured; crucially, not a crash


def test_dispatch_progress_is_logged(seeded_db, caplog):
    with caplog.at_level(logging.INFO):
        run_weekly_telemetry_check()

    messages = " ".join(r.getMessage() for r in caplog.records if r.name == "data.alert_worker")
    assert "10 engineers" in messages
    assert "skipped" in messages
