"""ARCH-02: scheduled alerts via an authenticated tick endpoint (called by a GitHub Actions cron)."""
from datetime import datetime, timezone

import pytest

import api.routes as routes
from tests.conftest import ADMIN_TOKEN

KOLKATA_FRIDAY_5PM = {"frequency": "Weekly", "day": "Friday", "time": "17:00", "timezone": "Asia/Kolkata"}
DUE = datetime(2026, 10, 2, 11, 40, tzinfo=timezone.utc)      # Fri 17:10 in Kolkata
NOT_DUE = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)    # Fri 14:30 in Kolkata
HEADERS = {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture
def scheduled(client, seeded_db, admin_token, monkeypatch):
    """A Friday 17:00 Kolkata schedule, with a clock we control and a stub dispatch."""
    assert client.post("/api/settings", json=KOLKATA_FRIDAY_5PM, headers=HEADERS).status_code == 200
    clock = {"now": DUE}
    monkeypatch.setattr(routes, "_utcnow", lambda: clock["now"])
    calls = []

    def fake_run():
        calls.append(1)
        return {"engineers": 1, "developer_emails": {"sent": 1, "failed": 0, "skipped": 0},
                "failed_recipients": [], "manager_digest": "sent", "slack": "skipped"}

    monkeypatch.setattr(routes, "run_weekly_telemetry_check", fake_run)
    return clock, calls


def tick(client):
    return client.post("/api/scheduled-tick", headers=HEADERS)


# ── settings carry a timezone ───────────────────────────────────────────────

def test_settings_round_trip_includes_timezone(client, admin_headers):
    client.post("/api/settings", json=KOLKATA_FRIDAY_5PM, headers=admin_headers)
    assert client.get("/api/settings").json() == KOLKATA_FRIDAY_5PM


def test_settings_timezone_defaults_to_utc_for_older_clients(client, admin_headers):
    client.post("/api/settings", json={"frequency": "Daily", "day": "Monday", "time": "08:00"},
                headers=admin_headers)
    assert client.get("/api/settings").json()["timezone"] == "UTC"


def test_unknown_timezone_is_rejected(client, admin_headers):
    response = client.post("/api/settings", json={**KOLKATA_FRIDAY_5PM, "timezone": "Mars/Olympus_Mons"},
                           headers=admin_headers)
    assert response.status_code == 422


def test_existing_database_gains_the_timezone_column(tmp_path, monkeypatch):
    import sqlite3

    from core.db import init_db, get_db_connection

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE alert_settings (id INTEGER PRIMARY KEY CHECK (id = 1), frequency TEXT NOT NULL,
                                     day TEXT, time TEXT NOT NULL);
        INSERT INTO alert_settings VALUES (1, 'Weekly', 'Monday', '10:00');
    """)
    conn.close()
    monkeypatch.setenv("DB_PATH", str(db))

    init_db()
    init_db()  # idempotent

    conn = get_db_connection()
    row = dict(conn.execute("SELECT * FROM alert_settings").fetchone())
    conn.close()
    assert row == {"id": 1, "frequency": "Weekly", "day": "Monday", "time": "10:00", "timezone": "UTC"}


# ── the tick endpoint ───────────────────────────────────────────────────────

def test_tick_requires_admin_token(client, admin_token):
    assert client.post("/api/scheduled-tick").status_code == 401


def test_tick_before_the_slot_does_nothing(client, scheduled):
    clock, calls = scheduled
    clock["now"] = NOT_DUE

    response = tick(client)

    assert response.status_code == 200
    assert response.json()["status"] == "not_due"
    assert calls == []


def test_tick_in_the_slot_starts_a_scheduled_run(client, scheduled):
    _, calls = scheduled

    response = tick(client)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "started"
    assert body["slot"] == "2026-10-02T11:30:00+00:00"
    run = client.get(body["status_url"]).json()
    assert run["trigger"] == "schedule" and run["status"] == "success"
    assert calls == [1]


def test_repeated_ticks_send_the_slot_only_once(client, scheduled):
    clock, calls = scheduled

    first = tick(client)
    clock["now"] = DUE.replace(minute=55)   # next cron run, same slot
    second = tick(client)

    assert first.status_code == 202
    assert second.status_code == 200 and second.json()["status"] == "already_sent"
    assert calls == [1]


def test_tick_while_a_manual_dispatch_runs_retries_on_the_next_tick(client, scheduled):
    from core.dispatch import finish_run, start_run

    _, calls = scheduled
    manual = start_run("manual")

    busy = tick(client)
    finish_run(manual, "success", None)
    retried = tick(client)

    assert busy.status_code == 200 and busy.json()["status"] == "busy"
    assert retried.status_code == 202   # the slot was not consumed by the busy tick
    assert calls == [1]


def test_scheduled_run_is_not_blocked_by_the_manual_cooldown(client, scheduled):
    from core.dispatch import finish_run, start_run

    finish_run(start_run("manual"), "success", None)   # an admin just sent alerts by hand

    assert tick(client).status_code == 202


def test_tick_without_usage_data_does_not_consume_the_slot(client, empty_db, admin_token, monkeypatch):
    client.post("/api/settings", json=KOLKATA_FRIDAY_5PM, headers=HEADERS)
    monkeypatch.setattr(routes, "_utcnow", lambda: DUE)

    response = tick(client)

    assert response.status_code == 200 and response.json()["status"] == "no_data"


# ── data/clock.py: local stand-in for the GitHub cron, same decision path ───

def test_local_clock_tick_runs_a_due_slot_once(client, scheduled):
    from data import clock

    _, calls = scheduled

    first = clock.tick_once()
    second = clock.tick_once()

    assert first["status"] == "started" and second["status"] == "already_sent"
    assert calls == [1]
