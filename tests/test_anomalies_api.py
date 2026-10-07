"""UPG-07: spend anomalies in the API, on the engineer page, in the seed and in the manager digest."""
from datetime import date

import pytest

import data.alert_worker as worker
from data.seed import generate_historical_data

END = date(2026, 3, 31)


@pytest.fixture
def team_with_incidents(empty_db):
    generate_historical_data(days_back=60, num_engineers=10, end_date=END, incidents=4)


def test_incidents_are_injected_in_the_last_two_weeks_only(tmp_path, monkeypatch):
    from core.db import get_db_connection

    def rows(name, incidents):
        monkeypatch.setenv("DB_PATH", str(tmp_path / name))
        generate_historical_data(days_back=60, num_engineers=10, end_date=END, incidents=incidents)
        conn = get_db_connection()
        out = {(r["user_id"], r["date"]): tuple(r) for r in conn.execute(
            "SELECT user_id, date, input_tokens, cache_read_tokens, output_tokens FROM usage_metrics")}
        conn.close()
        return out

    plain, injected = rows("a.db", 0), rows("b.db", 4)
    changed = [k for k in plain if plain[k] != injected[k]]
    assert len(changed) == 4
    assert all(k[1] >= "2026-03-18" for k in changed)


def test_anomalies_lists_the_flagged_days(client, team_with_incidents):
    body = client.get("/api/anomalies?days=14").json()

    assert body["days"] == 14
    assert body["anomalies"], "the injected incidents should be found"
    first = body["anomalies"][0]
    assert {"user_id", "name", "date", "cost_usd", "baseline_median_usd", "excess_usd", "z", "driver",
            "driver_label"} <= set(first)
    assert all(a["date"] >= "2026-03-18" for a in body["anomalies"])
    assert all(a["excess_usd"] >= 5 and a["z"] >= 3.5 for a in body["anomalies"])


def test_no_data_means_no_anomalies(client, empty_db):
    assert client.get("/api/anomalies").json() == {"days": 14, "anomalies": []}


@pytest.mark.parametrize("days", [0, 91])
def test_days_is_bounded(client, empty_db, days):
    assert client.get(f"/api/anomalies?days={days}").status_code == 422


def test_engineer_details_mark_their_anomaly_days(client, team_with_incidents):
    anomaly = client.get("/api/anomalies?days=14").json()["anomalies"][0]

    body = client.get(f"/api/engineer/{anomaly['user_id']}/details").json()

    assert anomaly["date"] in [a["date"] for a in body["anomalies"]]


def test_the_manager_digest_lists_recent_anomalies(team_with_incidents, monkeypatch):
    sent = {}
    monkeypatch.setattr(worker, "send_developer_alert", lambda dev, session=None: "sent")
    monkeypatch.setattr(worker, "send_daily_report", lambda **kw: sent.update(kw) or "sent")

    worker.run_weekly_telemetry_check()

    assert sent["anomalies"] and {"name", "date", "excess_usd", "driver_label"} <= set(sent["anomalies"][0])


def test_the_digest_template_shows_anomalies():
    from notifications.email_report import render_email_html

    html = render_email_html([], [], 50.0, 10.0, "memo", anomalies=[
        {"name": "Ada", "date": "2026-03-30", "cost_usd": 61.5, "baseline_median_usd": 12.0, "excess_usd": 49.5,
         "driver_label": "more tokens (e.g. a runaway agent loop)"}])

    assert "Spend anomalies" in html and "Ada" in html and "$61.50" in html and "runaway agent loop" in html
    assert "Spend anomalies" not in render_email_html([], [], 50.0, 10.0, "memo")
