"""UPG-03: the sensitivity analysis is itself tested."""
import pytest

from analysis.weight_sensitivity import kendall_tau, ranking, run, simulate_team
from core.scorer import AREA_WEIGHTS, calculate_efficiency_score, score_breakdown


@pytest.mark.parametrize("a, b, tau", [
    (["a", "b", "c", "d"], ["a", "b", "c", "d"], 1.0),
    (["a", "b", "c", "d"], ["d", "c", "b", "a"], -1.0),
    (["a", "b", "c", "d"], ["b", "a", "c", "d"], 4 / 6),   # one swapped pair out of 6
])
def test_kendall_tau(a, b, tau):
    assert kendall_tau(a, b) == pytest.approx(tau)


def test_default_weights_reproduce_the_stored_scores():
    team = simulate_team(seed=3)
    days = team["e0"]
    explicit = score_breakdown(days[-1], days[-7:-1], weights=dict(AREA_WEIGHTS))["total"]
    assert calculate_efficiency_score(days[-1], days[-7:-1]) == explicit


def test_doubling_a_weight_can_change_the_ranking():
    team = simulate_team(seed=3)
    assert ranking(team, AREA_WEIGHTS) != ranking(team, {**AREA_WEIGHTS, "model_mix": 300})


def test_run_reports_every_variant_and_baseline_is_identical():
    results = run(seeds=range(1, 4))
    assert len(results) == 7          # baseline + 3 areas x (-20%, +20%)
    assert results[0]["mean_tau"] == 1.0 and results[0]["bottom2_unchanged"] == 1.0
    assert all(-1 <= r["min_tau"] <= r["mean_tau"] <= 1 for r in results)
