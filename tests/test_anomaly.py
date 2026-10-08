"""UPG-07: spend anomalies against each engineer's own normal, weekdays and weekends apart."""
from datetime import date, timedelta

import pytest

from core.anomaly import BASELINE_DAYS, MIN_BASELINE, detect

START = date(2026, 3, 3)   # a Tuesday: day 40 is a Sunday, day 41 a Monday


def usage(prompt=9_000_000, hit=0.7, opus=0.3, output_ratio=0.012):
    write = int(prompt * 0.04)
    read = int(prompt * hit)
    return {"input_tokens": prompt - read - write, "cache_read_tokens": read, "cache_write_tokens": write,
            "output_tokens": int(prompt * output_ratio), "opus_pct": opus, "sonnet_pct": round(0.9 - opus, 2),
            "haiku_pct": 0.1}


def history(n=42, weekend_factor=0.3, wobble=(0.9, 1.0, 1.1, 0.95, 1.05), habits=None, **last):
    """n days of steady usage (weekends at 30% volume, a little day-to-day wobble, usage() `habits`);
    the last day can be overridden with **last (usage() arguments)."""
    habits = habits or {}
    days = []
    for i in range(n):
        d = START + timedelta(days=i)
        factor = (weekend_factor if d.weekday() >= 5 else 1.0) * wobble[i % len(wobble)]
        days.append({"date": d, **usage(**{**habits, "prompt": int(9_000_000 * factor)})})
    if last:
        base = 9_000_000 * (weekend_factor if days[-1]["date"].weekday() >= 5 else 1.0)
        days[-1] = {"date": days[-1]["date"], **usage(**{**habits, "prompt": int(base), **last})}
    return days


def last_result(days):
    return detect(days)[-1]


def test_a_normal_day_is_not_flagged():
    assert last_result(history())["flagged"] is False


def test_a_runaway_loop_is_flagged_with_volume_as_the_driver():
    result = last_result(history(prompt=40_000_000))
    assert result["flagged"] and result["driver"] == "volume"
    assert result["excess_usd"] > 0 and result["z"] >= 3.5


def test_broken_caching_is_flagged_with_cache_as_the_driver():
    result = last_result(history(hit=0.05))
    assert result["flagged"] and result["driver"] == "cache"


def test_a_switch_to_opus_is_flagged_with_model_mix_as_the_driver():
    # An engineer with little caching, so the Opus premium on uncached input is real money.
    result = last_result(history(habits={"hit": 0.3, "opus": 0.1}, opus=0.85))
    assert result["flagged"] and result["driver"] == "model_mix"


def test_a_quiet_weekend_after_busy_weekdays_is_not_flagged_and_a_busy_one_is():
    # Day 40 is a Sunday. Compared with weekdays it is cheap; compared with weekends it is normal.
    days = history(n=41)
    assert days[-1]["date"].weekday() == 6
    assert last_result(days)["flagged"] is False
    busy_sunday = history(n=41, prompt=9_000_000)      # a weekday's volume on a Sunday: 3.3x normal
    assert last_result(busy_sunday)["flagged"] is True


def test_a_weekday_spike_is_judged_against_weekdays_only():
    # A weekday at 1.6x: unusual for weekdays, but a mean that mixed in weekends would call it 3x.
    assert last_result(history(prompt=int(9_000_000 * 1.6)))["flagged"] is True
    assert last_result(history(prompt=int(9_000_000 * 1.15)))["flagged"] is False


def test_small_absolute_changes_are_not_flagged_even_if_unusual():
    # A light user doubling a ~$2 day is statistically odd but not worth anyone's attention.
    days = [{**d, **{k: d[k] // 5 for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens",
                                                  "output_tokens")}} for d in history(prompt=18_000_000)]
    result = last_result(days)
    assert result["z"] >= 3.5 and result["flagged"] is False


def test_short_history_is_not_evaluated():
    results = detect(history(n=10))      # at most 7 weekdays before any day
    assert all(r["evaluated"] is False and r["flagged"] is False for r in results)
    assert BASELINE_DAYS == 28 and MIN_BASELINE == 8


def test_a_past_incident_does_not_hide_the_next_one():
    # Median/MAD: one earlier spike in the baseline barely moves it (a mean/std baseline would be inflated).
    days = history(n=42, prompt=40_000_000)
    days[35] = {"date": days[35]["date"], **usage(prompt=40_000_000)}
    assert last_result(days)["flagged"]


def test_dates_can_be_iso_strings_and_unsorted():
    days = history(prompt=40_000_000)
    shuffled = [{**d, "date": d["date"].isoformat()} for d in reversed(days)]
    assert detect(shuffled)[-1]["date"] == days[-1]["date"].isoformat()
    assert detect(shuffled)[-1]["flagged"]


@pytest.mark.parametrize("cost_field", [True, False])
def test_stored_cost_is_used_when_present(cost_field):
    days = history()
    if cost_field:
        days[-1]["estimated_cost_usd"] = 500.0
    assert last_result(days)["flagged"] is cost_field
