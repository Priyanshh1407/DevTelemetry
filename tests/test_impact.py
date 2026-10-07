"""UPG-05: did coaching work? Estimators on hand-built series where the right answer is known."""
from datetime import date, timedelta

import pytest

from core.impact import area_points, event_effects, summarize

D0 = date(2026, 5, 15)  # the coaching (selection) day


def cache_day(points):
    """A day whose cache score is exactly `points` (of 40)."""
    hit = points / 40
    return {"input_tokens": round(1_000_000 * (1 - hit)), "cache_read_tokens": round(1_000_000 * hit),
            "cache_write_tokens": 0, "output_tokens": 1_000, "opus_pct": 0.2, "sonnet_pct": 0.6,
            "haiku_pct": 0.2, "session_count": 4, "compact_uses": 2}


def series(values_by_offset, default):
    """Days D0-20 .. D0+10: `default` points, except the offsets given."""
    return {D0 + timedelta(days=k): cache_day(values_by_offset.get(k, default)) for k in range(-20, 11)}


def event(user="a", day=D0, area="cache"):
    return {"user_id": user, "coached_on": day, "target_area": area}


def test_pure_regression_to_the_mean_fools_naive_but_not_did():
    # A has a stable habit (20 points); the coaching day was just a bad day. Nothing changes after.
    team = {"a": series({0: 10}, 20), "b": series({}, 20), "c": series({}, 20)}

    [e] = event_effects(team, [event()])

    assert e["status"] == "included"
    assert e["naive"] == pytest.approx(10)       # "coaching gained 10 points": pure selection artefact
    assert e["pre_post"] == pytest.approx(0)
    assert e["did"] == pytest.approx(0)


def test_a_real_shift_is_recovered_and_a_team_wide_trend_is_removed():
    # Everyone gains 2 points after D0 (a tooling change); A, who was coached, gains 5 more.
    after = {k: 22 for k in range(1, 11)}
    a = {**{k: 27 for k in range(1, 11)}, 0: 12}
    team = {"a": series(a, 20), "b": series(after, 20), "c": series(after, 20)}

    [e] = event_effects(team, [event()])

    assert e["pre_post"] == pytest.approx(7)     # 5 from coaching + 2 the whole team got anyway
    assert e["control_change"] == pytest.approx(2)
    assert e["did"] == pytest.approx(5)
    assert e["n_controls"] == 2


def test_the_baseline_skips_the_days_pooled_into_the_selection_day():
    # Days -6..-1 feed the selection day's 7-day /compact score, so they are selected too.
    # A dip there must not leak into the baseline.
    dips = {k: 5 for k in range(-6, 0)}
    team = {"a": series(dips, 20), "b": series({}, 20)}

    [e] = event_effects(team, [event()])

    assert e["before"] == pytest.approx(20)


def test_outcome_is_the_targeted_area_on_that_day_only():
    day = {**cache_day(20), "session_count": 4, "compact_uses": 4}
    assert area_points(day, "discipline") == 30          # not pooled with any other day
    assert area_points(day, "cache") == 20
    assert area_points({**day, "session_count": 0, "compact_uses": 0}, "discipline") is None


@pytest.mark.parametrize("other_event_offset", [-7, -13, 3])
def test_overlapping_coaching_is_excluded(other_event_offset):
    team = {"a": series({}, 20), "b": series({}, 20)}
    events = [event(), event(day=D0 + timedelta(days=other_event_offset))]

    effects = {e["coached_on"]: e for e in event_effects(team, events)}

    assert effects[D0]["status"] == "overlapping coaching"


def test_coaching_two_weeks_apart_is_not_overlapping():
    team = {"a": series({}, 20), "b": series({}, 20)}
    effects = event_effects(team, [event(), event(day=D0 - timedelta(days=14))])
    assert {e["coached_on"]: e["status"] for e in effects}[D0] == "included"


def test_engineers_coached_in_the_window_are_not_controls():
    team = {"a": series({}, 20), "b": series({}, 20), "c": series({}, 20)}
    [main, _] = event_effects(team, [event(), event(user="b", day=D0 - timedelta(days=3))])
    assert main["n_controls"] == 1


def test_events_without_enough_data_or_comparison_are_excluded():
    short = {D0 + timedelta(days=k): cache_day(20) for k in range(-2, 8)}
    assert event_effects({"a": short, "b": series({}, 20)}, [event()])[0]["status"] == "insufficient data"
    assert event_effects({"a": series({}, 20)}, [event()])[0]["status"] == "no comparison group"


def test_summary_reports_each_method_with_a_confidence_interval():
    team = {u: series({}, 20) for u in "abcdef"}
    team["a"] = series({**{k: 26 for k in range(1, 11)}, 0: 10}, 20)      # coached on D0: +6
    team["b"] = series({**{k: 24 for k in range(2, 11)}, 1: 12}, 20)      # coached the next day: +4
    events = [event("a"), event("b", day=D0 + timedelta(days=1))]

    summary = summarize(event_effects(team, events))

    assert summary["n_events"] == 2 and summary["n_excluded"] == 0
    assert summary["did"]["estimate"] == pytest.approx(5)
    assert summary["naive"]["estimate"] == pytest.approx(14)
    assert summary["did"]["ci_low"] <= 5 <= summary["did"]["ci_high"]
    assert summarize(event_effects(team, events)) == summary   # fixed bootstrap seed: same answer


def test_one_coaching_day_gives_an_estimate_but_no_interval():
    # Events on the same day share their comparison group, so they are resampled together;
    # one such cluster can't say anything about uncertainty.
    team = {u: series({}, 20) for u in "abc"}
    team["a"] = series({k: 25 for k in range(1, 11)}, 20)
    summary = summarize(event_effects(team, [event("a")]))
    assert summary["did"]["estimate"] == pytest.approx(5) and summary["did"]["ci_low"] is None


def test_summary_of_nothing():
    summary = summarize([])
    assert summary["n_events"] == 0 and summary["did"]["estimate"] is None
