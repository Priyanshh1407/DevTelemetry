"""UPG-05: the validation study's ground truth and report (the full run is python -m analysis.coaching_impact)."""
from analysis.coaching_impact import report, run, simulate_team


def test_with_no_effect_the_truth_is_exactly_zero():
    _, events, truth = simulate_team(seed=1, effect="none", days=60)
    assert events and all(t == 0 for t in truth.values() if t is not None)


def test_with_an_effect_the_truth_is_never_negative_and_sometimes_positive():
    _, _, truth = simulate_team(seed=1, effect="moderate", days=60)
    values = [t for t in truth.values() if t is not None]
    assert min(values) >= 0 and max(values) > 0


def test_the_simulation_is_deterministic():
    assert simulate_team(seed=3, effect="moderate", days=45) == simulate_team(seed=3, effect="moderate", days=45)


def test_report_has_a_row_per_method():
    text = report(run(teams=3))
    for name in ("Naive", "Before/after", "Difference-in-differences"):
        assert text.count(name) == 2          # one row per scenario
