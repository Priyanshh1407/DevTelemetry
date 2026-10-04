"""The fixed eval set: 30 engineer profiles (one latest day + 6 earlier days each).

Each of the three score areas (cache, model_mix, discipline) is the weakest area in 10
profiles, and severities cycle low / moderate / critical, so the set covers every
combination the coaching prompt has to handle. Profiles are generated once with a fixed
seed and committed as evals/profiles.json; regenerate only deliberately:

    python -m evals.profiles
"""
import json
import pathlib
import random

from ai.features import coaching_facts

PROFILES_PATH = pathlib.Path(__file__).with_name("profiles.json")
AREAS = ("cache", "model_mix", "discipline")
SEVERITIES = ("low", "moderate", "critical")

# Habit ranges that make one area clearly the weakest.
RANGES = {
    "cache":      {"hit": (0.08, 0.35), "opus": (0.05, 0.25), "compact": (0.55, 0.95)},
    "model_mix":  {"hit": (0.70, 0.92), "opus": (0.60, 0.90), "compact": (0.55, 0.95)},
    "discipline": {"hit": (0.70, 0.92), "opus": (0.05, 0.25), "compact": (0.00, 0.15)},
}


def _day(rng, date, area):
    r = RANGES[area]
    prompt = rng.randint(4_000_000, 14_000_000)
    read = int(prompt * rng.uniform(*r["hit"]))
    write = int(prompt * rng.uniform(0.02, 0.05))
    opus = rng.uniform(*r["opus"])
    haiku = rng.uniform(0.05, max(0.06, 0.9 - opus) * 0.4)
    sessions = rng.randint(2, 7)
    return {
        "date": date,
        "input_tokens": prompt - read - write,
        "cache_read_tokens": read,
        "cache_write_tokens": write,
        "output_tokens": int(prompt * rng.uniform(0.006, 0.02)),
        "opus_pct": round(opus, 2),
        "haiku_pct": round(haiku, 2),
        "sonnet_pct": round(1 - round(opus, 2) - round(haiku, 2), 2),
        "session_count": sessions,
        "compact_uses": sum(rng.random() < rng.uniform(*r["compact"]) for _ in range(sessions)),
        "estimated_cost_usd": round(prompt / 1_000_000 * rng.uniform(0.8, 1.6), 2),
        "git_commits": rng.randint(0, 9),
    }


def generate(seed=2026, n_per_area=10):
    rng = random.Random(seed)
    profiles = []
    for i in range(n_per_area * len(AREAS)):
        area = AREAS[i % len(AREAS)]
        severity = SEVERITIES[(i // len(AREAS)) % len(SEVERITIES)]
        while True:  # resample until the intended area really is the weakest
            days = [_day(rng, f"2026-03-{25 + d:02d}", area) for d in range(7)]
            if coaching_facts(days[-1], days[:-1])["weakest_area"] == area:
                break
        profiles.append({"id": f"p{i + 1:02d}", "weakest_area": area, "severity": severity,
                         "day": days[-1], "recent": days[:-1]})
    return profiles


def load():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    PROFILES_PATH.write_text(json.dumps(generate(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {PROFILES_PATH}")  # noqa: T201
