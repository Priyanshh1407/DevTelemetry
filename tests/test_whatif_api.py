"""UPG-06: GET /api/engineer/{id}/what-if."""
import pytest

from tests.conftest import engineer_id


def test_defaults_to_the_teams_top_quartile_habits(client, seeded_db):
    body = client.get(f"/api/engineer/{engineer_id(0)}/what-if").json()

    assert body["targets"] == body["team_targets"]
    assert set(body["team_targets"]) == {"cache_hit", "opus_pct"}
    assert set(body["current"]) == {"cache_hit", "opus_pct"}
    assert body["days"] == 3 and body["period_days"] == 30
    # eng-00 has the team's worst cache ratio, so reaching the top quartile saves money.
    assert body["cache"]["saving_month_usd"] > 0
    assert body["combined"]["projected_month_usd"] <= body["current_month_usd"]


def test_explicit_targets(client, seeded_db):
    body = client.get(f"/api/engineer/{engineer_id(0)}/what-if?cache_hit=0.9&opus_pct=0.05").json()
    assert body["targets"] == {"cache_hit": 0.9, "opus_pct": 0.05}
    assert body["model"]["saving_month_usd"] > 0


@pytest.mark.parametrize("query", ["cache_hit=0.99", "cache_hit=-1", "opus_pct=2", "opus_pct=abc"])
def test_invalid_targets_answer_422(client, seeded_db, query):
    assert client.get(f"/api/engineer/{engineer_id(0)}/what-if?{query}").status_code == 422


def test_unknown_engineer_answers_404(client, seeded_db):
    assert client.get("/api/engineer/nobody/what-if").status_code == 404
