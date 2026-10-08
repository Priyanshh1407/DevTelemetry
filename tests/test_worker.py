"""TEST-01a: what the alert worker sends, to whom, with which severity and waste pattern."""
import pytest

import data.alert_worker as worker
from core.db import db_session


def make_team(scores, opus_pcts=None, date="2026-01-01"):
    """Inserts one engineer per score for a single day (best score = rank 1)."""
    opus_pcts = opus_pcts or [0.2] * len(scores)
    with db_session() as conn:
        for i, (score, opus) in enumerate(zip(scores, opus_pcts, strict=True)):
            conn.execute("INSERT INTO engineers (user_id, name, email) VALUES (?, ?, ?)",
                         (f"u{i}", f"Dev {i}", f"dev{i}@example.com"))
            conn.execute("""INSERT INTO usage_metrics (user_id, date, input_tokens, cache_read_tokens, opus_pct,
                            sonnet_pct, haiku_pct, session_count, compact_uses, estimated_cost_usd, efficiency_score)
                            VALUES (?, ?, 1000, 500, ?, 0.5, ?, 2, 1, 1.0, ?)""",
                         (f"u{i}", date, opus, round(0.5 - opus, 2), score))


@pytest.fixture
def captured(monkeypatch):
    """Records every developer alert and the manager digest instead of sending them."""
    sent = {"alerts": [], "digest": None}

    def fake_alert(dev, session=None):
        sent["alerts"].append(dict(dev))
        return "sent"

    def fake_digest(**kwargs):
        sent["digest"] = kwargs
        return "sent"

    monkeypatch.setattr(worker, "send_developer_alert", fake_alert)
    monkeypatch.setattr(worker, "send_daily_report", fake_digest)
    return sent


@pytest.mark.parametrize("team_size, expected", [
    (10, ["low"] * 5 + ["moderate"] * 3 + ["critical"] * 2),
    (7, ["low"] * 5 + ["critical"] * 2),
    (3, ["low"] * 3),  # documented quirk: small teams have nobody critical
])
def test_every_engineer_gets_an_alert_with_rank_and_severity(empty_db, captured, team_size, expected):
    make_team([90 - i for i in range(team_size)])

    summary = worker.run_weekly_telemetry_check()

    alerts = captured["alerts"]
    assert [a["severity"] for a in alerts] == expected
    assert [a["rank"] for a in alerts] == list(range(1, team_size + 1))
    assert {a["total_devs"] for a in alerts} == {team_size}
    assert summary["developer_emails"]["sent"] == team_size


@pytest.mark.parametrize("opus_pct, score, pattern", [
    (0.6, 40, "Over-reliance on expensive Opus model"),       # Opus check wins over a low score
    (0.2, 40, "High token waste / Possible prompt looping"),
    (0.2, 70, "Low cache utilization"),
])
def test_digest_diagnoses_the_bottom_engineers_waste_pattern(empty_db, captured, opus_pct, score, pattern):
    # Two strong engineers, then the two bottom engineers under test.
    make_team([95, 90, score + 1, score], opus_pcts=[0.1, 0.1, opus_pct, opus_pct])

    worker.run_weekly_telemetry_check()

    bottom = captured["digest"]["bottom_engineers"]
    assert [d["name"] for d in bottom] == ["Dev 2", "Dev 3"]
    assert {d["primary_waste_pattern"] for d in bottom} == {pattern}


def test_digest_reports_team_average_and_total_cost(empty_db, captured):
    make_team([80, 60, 40])

    worker.run_weekly_telemetry_check()

    digest = captured["digest"]
    assert digest["average_score"] == pytest.approx(60.0)
    assert digest["total_cost"] == pytest.approx(3.0)
    assert [d["name"] for d in digest["top_engineers"]] == ["Dev 0", "Dev 1", "Dev 2"]


def test_no_data_sends_nothing(empty_db, captured):
    summary = worker.run_weekly_telemetry_check()

    assert summary["engineers"] == 0
    assert captured["alerts"] == [] and captured["digest"] is None
    assert worker.overall_status(summary) == "no_data"


def test_only_the_latest_day_is_alerted(empty_db, captured):
    make_team([50, 40], date="2026-01-01")
    with db_session() as conn:
        conn.execute("""INSERT INTO usage_metrics (user_id, date, input_tokens, cache_read_tokens, opus_pct,
                        sonnet_pct, haiku_pct, session_count, compact_uses, estimated_cost_usd, efficiency_score)
                        VALUES ('u1', '2026-01-02', 1000, 500, 0.2, 0.5, 0.3, 2, 1, 1.0, 99)""")

    worker.run_weekly_telemetry_check()

    assert [a["user_id"] for a in captured["alerts"]] == ["u1"]


# ── UPG-05: the worker records who was coached ──────────────────────────────

def test_sent_critical_alerts_are_recorded_as_coaching(empty_db, captured, query):
    make_team([90 - i for i in range(10)])

    worker.run_weekly_telemetry_check()

    events = query("SELECT user_id, coached_on, severity, target_area, source FROM coaching_events ORDER BY user_id")
    assert [e["user_id"] for e in events] == ["u8", "u9"]          # the two critical engineers
    assert {(e["coached_on"], e["severity"], e["source"]) for e in events} == {("2026-01-01", "critical", "dispatch")}
    assert {e["target_area"] for e in events} <= {"cache", "model_mix", "discipline"}


def test_a_critical_alert_that_was_not_sent_is_not_coaching(empty_db, captured, query, monkeypatch):
    make_team([90 - i for i in range(10)])
    monkeypatch.setattr(worker, "send_developer_alert",
                        lambda dev, session=None: "failed" if dev["user_id"] == "u9" else "sent")

    worker.run_weekly_telemetry_check()

    assert [e["user_id"] for e in query("SELECT user_id FROM coaching_events")] == ["u8"]


def test_dispatching_twice_for_the_same_day_records_one_coaching(empty_db, captured, query):
    make_team([90 - i for i in range(10)])

    worker.run_weekly_telemetry_check()
    worker.run_weekly_telemetry_check()

    assert query("SELECT COUNT(*) AS n FROM coaching_events")[0]["n"] == 2
