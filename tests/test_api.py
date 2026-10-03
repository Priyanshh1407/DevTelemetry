"""Characterization tests for the read API and settings.

They pin down current behavior against a deterministic temporary DB (see conftest.py),
so later phases can change internals without silently changing responses.
Known bugs from the audit are recorded as strict xfails: when a fix lands, the xfail
starts passing, pytest reports XPASS as a failure, and the marker must be removed.
"""
import pytest

from tests.conftest import LATEST_DATE, NUM_ENGINEERS, engineer_id, seed_db


def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "API is running"}


# ── /api/leaderboard ────────────────────────────────────────────────────────

def test_leaderboard_empty_db_returns_empty_list(client):
    response = client.get("/api/leaderboard")
    assert response.status_code == 200
    assert response.json() == []


def test_leaderboard_ranks_latest_day_by_score(client, seeded_db, query):
    data = client.get("/api/leaderboard").json()

    assert len(data) == NUM_ENGINEERS
    assert [row["user_id"] for row in data] == [engineer_id(i) for i in reversed(range(NUM_ENGINEERS))]
    assert set(data[0]) == {"name", "user_id", "efficiency_score", "estimated_cost_usd",
                            "input_tokens", "output_tokens",
                            "score_change_7d", "recent_activity"}  # added in BUG-07

    latest_scores = {r["user_id"]: r["efficiency_score"] for r in query(
        "SELECT user_id, efficiency_score FROM usage_metrics WHERE date = ?", (LATEST_DATE,))}
    assert {row["user_id"]: row["efficiency_score"] for row in data} == latest_scores


# ── /api/trends ─────────────────────────────────────────────────────────────

def test_trends_returns_daily_team_aggregates(client, seeded_db, query):
    data = client.get("/api/trends").json()

    expected = query("""SELECT date, ROUND(AVG(efficiency_score), 2) AS avg_score,
                               ROUND(SUM(estimated_cost_usd), 2) AS total_cost
                        FROM usage_metrics GROUP BY date ORDER BY date""")
    assert data == expected
    assert [d["date"] for d in data] == ["2026-01-01", "2026-01-02", LATEST_DATE]


def test_trends_window_ends_at_latest_date(client, empty_db):
    seed_db(num_days=40)
    data = client.get("/api/trends").json()

    assert len(data) == 30
    assert data[-1]["date"] == "2026-02-09"


def test_details_history_is_latest_30_days_in_order(client, empty_db):
    seed_db(num_days=40)
    data = client.get(f"/api/engineer/{engineer_id(3)}/details").json()

    dates = [h["date"] for h in data["history"]]
    assert len(dates) == 30
    assert dates[0] == "2026-01-11" and dates[-1] == "2026-02-09"
    assert dates == sorted(dates)
    assert data["latest"]["efficiency_score"] == data["history"][-1]["efficiency_score"]


# ── /api/engineer/{id}/details ──────────────────────────────────────────────

def test_details_unknown_engineer_returns_404(client, seeded_db):
    response = client.get("/api/engineer/nonexistent_id/details")
    assert response.status_code == 404
    assert response.json() == {"detail": "Engineer not found"}


def test_details_engineer_without_usage_returns_404(client, seeded_db, query):
    from core.db import get_db_connection

    conn = get_db_connection()
    conn.execute("INSERT INTO engineers (user_id, name, email) VALUES ('new', 'New Hire', 'n@example.com')")
    conn.commit()
    conn.close()

    response = client.get("/api/engineer/new/details")
    assert response.status_code == 404
    assert response.json() == {"detail": "No usage history found for this engineer"}


@pytest.mark.parametrize("index, rank, severity", [
    (9, 1, "low"),
    (5, 5, "low"),
    (4, 6, "moderate"),
    (2, 8, "moderate"),
    (1, 9, "critical"),
    (0, 10, "critical"),
])
def test_details_rank_and_severity_tiers(client, seeded_db, index, rank, severity):
    data = client.get(f"/api/engineer/{engineer_id(index)}/details").json()

    assert data["current_rank"] == rank
    assert data["current_severity"] == severity


def test_details_history_averages_and_patterns(client, seeded_db, query):
    data = client.get(f"/api/engineer/{engineer_id(3)}/details").json()

    assert data["name"] == "Engineer 03"
    assert [h["date"] for h in data["history"]] == ["2026-01-01", "2026-01-02", LATEST_DATE]

    rows = query("SELECT * FROM usage_metrics WHERE user_id = ? ORDER BY date", (engineer_id(3),))
    for h, row in zip(data["history"], rows, strict=True):
        assert h["cache_ratio"] == round(row["cache_read_tokens"] / row["input_tokens"], 4)

    assert data["averages"]["avg_score"] == round(sum(r["efficiency_score"] for r in rows) / 3, 2)
    assert data["averages"]["total_commits"] == 3 * 3
    assert data["latest"]["efficiency_score"] == rows[-1]["efficiency_score"]
    assert [p["label"] for p in data["patterns"]] == ["Model Usage", "Cache Efficiency", "Session Discipline"]


# ── /api/settings ───────────────────────────────────────────────────────────

def test_settings_default_row_from_schema(client):
    assert client.get("/api/settings").json() == {"frequency": "Weekly", "day": "Friday", "time": "17:00", "timezone": "UTC"}


def test_settings_falls_back_when_row_missing(client, empty_db):
    from core.db import get_db_connection

    conn = get_db_connection()
    conn.execute("DELETE FROM alert_settings")
    conn.commit()
    conn.close()

    assert client.get("/api/settings").json() == {"frequency": "Weekly", "day": "Friday", "time": "17:00", "timezone": "UTC"}


def test_settings_update_round_trip(client, admin_headers):
    new = {"frequency": "Daily", "day": "Monday", "time": "09:30"}

    response = client.post("/api/settings", json=new, headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Schedule updated"}
    assert client.get("/api/settings").json() == {**new, "timezone": "UTC"}  # timezone added in ARCH-02


def test_settings_missing_field_is_rejected(client, admin_headers):
    assert client.post("/api/settings", json={"frequency": "Daily"}, headers=admin_headers).status_code == 422


def test_settings_invalid_values_are_rejected(client, admin_headers):
    response = client.post("/api/settings", json={"frequency": "Hourly", "day": "Funday", "time": "99:99"},
                           headers=admin_headers)
    assert response.status_code == 422


@pytest.mark.parametrize("field, bad_value", [
    ("frequency", "Hourly"),
    ("frequency", "Biweekly"),   # offered by the old UI but never implemented by any scheduler
    ("frequency", "Monthly"),
    ("day", "Funday"),
    ("time", "99:99"),
    ("time", "24:00"),
    ("time", "9:30"),
    ("time", "09:30; DROP TABLE"),
])
def test_settings_each_invalid_field_is_rejected_and_not_saved(client, admin_headers, field, bad_value):
    payload = {"frequency": "Weekly", "day": "Friday", "time": "17:00", field: bad_value}

    response = client.post("/api/settings", json=payload, headers=admin_headers)

    assert response.status_code == 422
    assert client.get("/api/settings").json() == {"frequency": "Weekly", "day": "Friday", "time": "17:00", "timezone": "UTC"}


@pytest.mark.parametrize("payload", [
    {"frequency": "Daily", "day": "Monday", "time": "00:00"},
    {"frequency": "Weekly", "day": "Sunday", "time": "23:59"},
])
def test_settings_valid_edge_values_are_accepted(client, admin_headers, payload):
    assert client.post("/api/settings", json=payload, headers=admin_headers).status_code == 200


def test_runbook_unknown_severity_is_rejected_without_calling_the_llm(client, seeded_db, mock_gemini):
    # Every distinct severity string used to be a new cache entry and a new paid LLM call.
    response = client.get(f"/api/runbook-tasks/anything-i-want/{engineer_id(0)}")

    assert response.status_code == 422
    mock_gemini.models.generate_content.assert_not_called()


# ── /api/guide and /api/runbook-tasks (Gemini mocked) ───────────────────────

def test_guide_unknown_engineer_returns_404(client, seeded_db):
    assert client.get("/api/guide/nonexistent_id").status_code == 404


def test_guide_returns_parsed_tasks_for_latest_day(client, seeded_db):
    data = client.get(f"/api/guide/{engineer_id(0)}").json()

    assert data["name"] == "Engineer 00"
    assert data["date"] == LATEST_DATE
    assert [t["desc"] for t in data["guide"]] == ["Mock tip one", "Mock tip two"]
    assert data["source"] == "ai"


def test_runbook_unknown_engineer_returns_placeholder_task(client, seeded_db):
    data = client.get("/api/runbook-tasks/critical/nonexistent_id").json()
    assert data == {"tasks": [{"title": "Data Missing", "desc": "No telemetry found for this user."}], "source": "none"}


def test_runbook_second_request_is_served_from_cache(client, seeded_db, mock_gemini):
    url = f"/api/runbook-tasks/critical/{engineer_id(0)}"

    first = client.get(url).json()
    second = client.get(url).json()

    assert first == second
    assert [t["desc"] for t in first["tasks"]] == ["Mock tip one", "Mock tip two"]
    mock_gemini.models.generate_content.assert_called_once()


def test_runbook_failed_generation_is_not_cached(client, seeded_db, mock_gemini):
    # BUG-02: an outage used to be cached as if it were a real answer.
    ok = mock_gemini.models.generate_content.return_value
    mock_gemini.models.generate_content.side_effect = [Exception("connection reset"), ok]
    url = f"/api/runbook-tasks/critical/{engineer_id(0)}"

    first = client.get(url).json()
    second = client.get(url).json()

    assert first["tasks"][0]["title"] == "AI Service Offline"
    assert [t["desc"] for t in second["tasks"]] == ["Mock tip one", "Mock tip two"]
    assert mock_gemini.models.generate_content.call_count == 2


def test_runbook_cache_refreshes_when_newer_data_arrives(client, seeded_db, mock_gemini):
    from core.db import get_db_connection

    url = f"/api/runbook-tasks/critical/{engineer_id(0)}"
    client.get(url)

    conn = get_db_connection()
    conn.execute("""INSERT INTO usage_metrics (user_id, date, input_tokens, cache_read_tokens, opus_pct,
                    sonnet_pct, haiku_pct, session_count, compact_uses, estimated_cost_usd, efficiency_score)
                    VALUES (?, '2026-01-04', 1000, 0, 0.3, 0.5, 0.2, 1, 0, 1.0, 10.0)""", (engineer_id(0),))
    conn.commit()
    conn.close()
    client.get(url)

    assert mock_gemini.models.generate_content.call_count == 2


# ── BUG-07: trend and activity come from data, not from list position / Math.random ──

def test_leaderboard_reports_real_7_day_score_change_and_activity(client, empty_db, query):
    seed_db(num_days=10)  # 2026-01-01 .. 2026-01-10

    rows = {r["user_id"]: r for r in client.get("/api/leaderboard").json()}

    for user_id, row in rows.items():
        history = query("SELECT date, efficiency_score, input_tokens FROM usage_metrics "
                        "WHERE user_id = ? ORDER BY date", (user_id,))
        latest = history[-1]["efficiency_score"]
        previous_week = [h["efficiency_score"] for h in history if "2026-01-03" <= h["date"] <= "2026-01-09"]
        assert row["score_change_7d"] == pytest.approx(round(latest - sum(previous_week) / 7, 2))
        assert row["recent_activity"] == [h["input_tokens"] for h in history[-7:]]


def test_leaderboard_trend_is_null_without_history(client, empty_db):
    seed_db(num_days=1)

    row = client.get("/api/leaderboard").json()[0]

    assert row["score_change_7d"] is None
    assert len(row["recent_activity"]) == 1


# ── TEST-01a: engineer-detail insights on both sides of each threshold ──────

def _insights_for(client, opus_pct, cache_read, compact_uses):
    from core.db import db_session

    with db_session() as conn:
        conn.execute("INSERT INTO engineers (user_id, name, email) VALUES ('x', 'X', 'x@example.com')")
        conn.execute("""INSERT INTO usage_metrics (user_id, date, input_tokens, cache_read_tokens, opus_pct,
                        sonnet_pct, haiku_pct, session_count, compact_uses, git_commits, estimated_cost_usd,
                        efficiency_score) VALUES ('x', '2026-01-01', 1000, ?, ?, 0.5, ?, 4, ?, 1, 1.0, 50)""",
                     (cache_read, opus_pct, round(0.5 - opus_pct, 2), compact_uses))
    return {p["label"]: p["insight"] for p in client.get("/api/engineer/x/details").json()["patterns"]}


def test_insights_flag_habits_outside_team_targets(client, empty_db):
    insights = _insights_for(client, opus_pct=0.40, cache_read=300, compact_uses=1)

    assert "above team target" in insights["Model Usage"]
    assert "room to improve" in insights["Cache Efficiency"]
    assert "recommend using /compact more often" in insights["Session Discipline"]


def test_insights_praise_habits_within_team_targets(client, empty_db):
    insights = _insights_for(client, opus_pct=0.10, cache_read=700, compact_uses=3)

    assert "within team target" in insights["Model Usage"]
    assert "strong reuse" in insights["Cache Efficiency"]
    assert "strong context management" in insights["Session Discipline"]


# ── Privacy: the LLM gets metrics, never identity ──────────────────────────

@pytest.mark.parametrize("path", [f"/api/guide/{engineer_id(4)}", f"/api/runbook-tasks/critical/{engineer_id(4)}"])
def test_llm_prompts_contain_no_name_or_email(client, seeded_db, mock_gemini, path):
    client.get(path)

    prompt = mock_gemini.models.generate_content.call_args.kwargs["contents"]
    assert "Engineer 04" not in prompt
    assert "@example.com" not in prompt
    assert "efficiency_score" in prompt  # the metrics are still there
