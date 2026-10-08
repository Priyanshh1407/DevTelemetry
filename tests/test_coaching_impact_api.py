"""UPG-05: GET /api/coaching-impact and coaching days on the engineer page."""
from datetime import date

import pytest

from data.seed import generate_historical_data

END = date(2026, 3, 31)


@pytest.fixture
def coached_team(empty_db):
    # 88 days: the last of the 6 rounds (day 84) has only 4 days after it.
    generate_historical_data(days_back=88, num_engineers=10, end_date=END, coaching_effect="moderate")


def test_impact_reports_every_method_with_events(client, coached_team):
    body = client.get("/api/coaching-impact?days=90").json()

    assert body["n_events"] + body["n_excluded"] == len(body["events"]) == 12   # 6 coaching rounds x 2
    for method in ("naive", "pre_post", "did"):
        assert set(body[method]) == {"estimate", "ci_low", "ci_high"}
    assert body["did"]["estimate"] is not None
    first = body["events"][0]
    assert {"name", "user_id", "coached_on", "target_area", "status", "before", "after", "did"} <= set(first)
    assert body["window"] == {"pre": [-13, -7], "post": [1, 7]}


def test_the_last_round_has_no_after_window_yet(client, coached_team):
    events = client.get("/api/coaching-impact?days=90").json()["events"]
    last_round = max(e["coached_on"] for e in events)
    assert {e["status"] for e in events if e["coached_on"] == last_round} == {"insufficient data"}


def test_days_limits_the_events(client, coached_team):
    events = client.get("/api/coaching-impact?days=30").json()["events"]
    assert events and all(e["coached_on"] >= "2026-03-01" for e in events)


def test_no_coaching_yet(client, empty_db):
    body = client.get("/api/coaching-impact").json()
    assert body["n_events"] == 0 and body["events"] == [] and body["did"]["estimate"] is None


@pytest.mark.parametrize("days", [0, 400])
def test_days_is_bounded(client, empty_db, days):
    assert client.get(f"/api/coaching-impact?days={days}").status_code == 422


def test_engineer_details_list_their_coaching_days(client, coached_team, query):
    event = query("SELECT user_id, coached_on, target_area FROM coaching_events ORDER BY coached_on DESC LIMIT 1")[0]

    body = client.get(f"/api/engineer/{event['user_id']}/details").json()

    assert {"date": event["coached_on"], "target_area": event["target_area"]} in body["coaching"]
