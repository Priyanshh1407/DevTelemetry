"""UPG-07: the detector evaluation (the full run is python -m analysis.anomaly_eval)."""
import random

import pytest

from analysis.anomaly_eval import evaluate, report, simulate_team
from data.seed import daily_metrics, flat_day, inject_incident, make_persona


def test_incidents_are_injected_at_known_positions_and_deterministically():
    team, incidents = simulate_team(seed=4, days=60)
    assert incidents and simulate_team(seed=4, days=60)[1] == incidents
    assert set(incidents.values()) <= {"runaway_loop", "cache_breakage"}


def test_incident_kinds_do_what_they_say():
    rng = random.Random(1)
    day = flat_day(daily_metrics(rng, make_persona(rng), __import__("datetime").date(2026, 3, 3)))
    prompt = day["input_tokens"] + day["cache_read_tokens"] + day["cache_write_tokens"]

    loop = inject_incident(day, "runaway_loop", random.Random(2))
    broken = inject_incident(day, "cache_breakage", random.Random(2))

    assert 3 <= loop["output_tokens"] / day["output_tokens"] <= 6.01
    assert broken["input_tokens"] + broken["cache_read_tokens"] + broken["cache_write_tokens"] == prompt
    assert broken["cache_read_tokens"] <= 0.15 * prompt
    with pytest.raises(ValueError):
        inject_incident(day, "meteor", rng)


def test_report_compares_the_three_detectors():
    text = report(evaluate(teams=2, days=60))
    for name in ("Robust", "Fixed $30/day", "Mean + 3 sd"):
        assert name in text
