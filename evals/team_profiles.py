"""The fixed eval set for the team memo (UPG-08): 15 simulated team-days.

Each profile is a team of 10 engineers with 7 days of usage (the latest day and the 6 before
it, the window team facts use), from the persona model in data/seed.py. Each score area is the
team's biggest gap in 5 profiles, and the count of recent spend anomalies cycles 0..3, so the
memo has to handle every case. Generated once with a fixed seed and committed as
evals/team_profiles.json; regenerate only deliberately:

    python -m evals.team_profiles
"""
import json
import pathlib
import random
from datetime import date, timedelta

from ai.team_memo import team_facts
from core.pricing import estimate_cost
from data.seed import daily_metrics, flat_day, make_persona

PROFILES_PATH = pathlib.Path(__file__).with_name("team_profiles.json")
AREAS = ("cache", "model_mix", "discipline")
LATEST = date(2026, 3, 31)

# Habits that make one area weak for most of the team.
WEAK = {"cache": {"cache_hit": (0.30, 0.60)}, "model_mix": {"opus_share": (0.50, 0.80)},
        "discipline": {"compact_rate": (0.00, 0.20)}}


def _team(rng, area):
    team = {}
    for e in range(10):
        persona = make_persona(rng)
        if e < 7:
            for key, (low, high) in WEAK[area].items():
                persona[key] = rng.uniform(low, high)
        days = []
        for k in range(7):
            day = flat_day(daily_metrics(rng, persona, LATEST - timedelta(days=6 - k)))
            mix = {key: day[key] for key in ("opus_pct", "sonnet_pct", "haiku_pct")}
            day["estimated_cost_usd"] = round(estimate_cost(day["input_tokens"], day["output_tokens"],
                                                            day["cache_read_tokens"], day["cache_write_tokens"],
                                                            mix), 4)
            day["date"] = (LATEST - timedelta(days=6 - k)).isoformat()
            days.append(day)
        team[f"e{e}"] = days
    return team


def generate(seed=2026, n=15):
    rng = random.Random(seed)
    profiles = []
    for i in range(n):
        area, anomalies = AREAS[i % len(AREAS)], i % 4
        while True:   # resample until the intended area really is the team's biggest gap
            team = _team(rng, area)
            if team_facts(team, anomalies)["biggest_area"] == area:
                break
        profiles.append({"id": f"t{i + 1:02d}", "biggest_area": area, "anomaly_count": anomalies, "team": team})
    return profiles


def load():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    PROFILES_PATH.write_text(json.dumps(generate(), indent=None) + "\n", encoding="utf-8")
    print(f"wrote {PROFILES_PATH}")  # noqa: T201
