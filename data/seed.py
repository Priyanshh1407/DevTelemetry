"""Synthetic telemetry generator.

Usage:
    python data/seed.py                 # add data (idempotent: same engineers, existing days kept)
    python data/seed.py --reset         # wipe engineers/usage/guides first (keeps alert settings)
    python data/seed.py --seed 7 --days 60 --engineers 12
    python data/seed.py --if-empty      # container start: seed only a fresh database
    python data/seed.py --coaching-effect none   # simulated coaching that changes nothing (default: moderate)
"""
import argparse
import random
import re
import uuid
from datetime import date, timedelta
from faker import Faker
import os
import sys

# Ensure Python can find our core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.features import coaching_facts
from core.coaching_log import record_coaching
from core.db import db_session, init_db
from core.ingest import UsageRecord, upsert_usage
from core.scorer import POOL_DAYS, score_breakdown
from core.severity import CRITICAL, severity_for_rank

DEFAULT_SEED = 42


def make_engineers(rng, fake, num_engineers):
    """Deterministic engineers: the same seed always yields the same IDs, names and emails,
    so re-running the seed tops up data instead of adding a new team."""
    engineers = []
    for _ in range(num_engineers):
        name = fake.name()
        # example.com is reserved for documentation (RFC 2606), so these synthetic addresses
        # can never reach a real inbox. (company.com is a real, third-party domain.)
        local_part = re.sub(r"[^a-z.]", "", name.lower().replace(" ", "."))
        engineers.append({
            "user_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "name": name,
            "email": f"{local_part}@example.com",
        })
    return engineers


# ── Persona model ───────────────────────────────────────────────────────────
# Each engineer has stable habits (drawn once) and each day adds noise around them, so
# rankings and "waste patterns" persist the way real habits do. Calibrated against
# https://code.claude.com/docs/en/costs: ~$13 per developer per active day on average,
# below $30 per active day for 90% of users. Claude Code traffic is dominated by cache
# reads (each request re-sends the conversation), hence high hit ratios and large volumes.
# These are simulation assumptions, not measurements.

# Median prompt tokens (incl. cache reads) per weekday. Tuned so the simulated weekday
# mean cost lands near the $13 benchmark with ML-01's price table.
BASE_DAILY_PROMPT_TOKENS = 9_000_000
WEEKEND_ACTIVITY = 0.35  # weekends have rows, at reduced volume


def make_persona(rng):
    """Latent habits for one engineer."""
    return {
        "volume": rng.lognormvariate(0, 0.45),     # relative activity level
        "cache_hit": rng.uniform(0.45, 0.93),      # share of prompt tokens served from cache
        "opus_share": rng.uniform(0.05, 0.60),
        "haiku_share": rng.uniform(0.03, 0.35),
        "compact_rate": rng.uniform(0.0, 0.9),     # chance a session uses /compact
        "sessions": rng.uniform(2.0, 7.0),         # mean sessions per day
        "output_ratio": rng.uniform(0.006, 0.02),  # output tokens per prompt token
        "write_ratio": rng.uniform(0.02, 0.06),    # cache-write tokens per prompt token
        "commit_rate": rng.uniform(0.3, 2.0),      # commits per session
    }


def _clip(value, low, high):
    return max(low, min(high, value))


def daily_metrics(rng, persona, day):
    """One engineer-day: the persona's habits plus day-to-day noise."""
    weekday_factor = 1.0 if day.weekday() < 5 else WEEKEND_ACTIVITY
    prompt_tokens = int(BASE_DAILY_PROMPT_TOKENS * persona["volume"] * weekday_factor * rng.lognormvariate(0, 0.3))
    cache_hit = _clip(rng.gauss(persona["cache_hit"], 0.04), 0.0, 0.97)

    # Model mix: persona shares jittered multiplicatively, then normalized and rounded so they sum to 1
    sonnet_share = max(0.05, 1.0 - persona["opus_share"] - persona["haiku_share"])
    raw = [s * rng.lognormvariate(0, 0.15) for s in (persona["opus_share"], sonnet_share, persona["haiku_share"])]
    total = sum(raw)
    opus_pct = round(raw[0] / total, 2)
    sonnet_pct = round(raw[1] / total, 2)
    haiku_pct = round(1.0 - opus_pct - sonnet_pct, 2)

    sessions = max(1, round(rng.gauss(persona["sessions"] * (1 if weekday_factor == 1 else 0.5), 1.0)))
    compacts = sum(rng.random() < persona["compact_rate"] for _ in range(sessions))  # binomial(sessions, rate)

    # Split the day's prompt tokens the way Anthropic's usage object reports them:
    # cache reads, cache writes, and the uncached rest (input_tokens).
    output_tokens = int(prompt_tokens * persona["output_ratio"] * rng.uniform(0.8, 1.2))
    cache_read = int(prompt_tokens * cache_hit)
    cache_write = min(int(prompt_tokens * persona["write_ratio"] * rng.uniform(0.8, 1.2)), prompt_tokens - cache_read)

    return {
        "input_tokens": prompt_tokens - cache_read - cache_write,  # uncached only
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "model_mix": {"opus_pct": opus_pct, "sonnet_pct": sonnet_pct, "haiku_pct": haiku_pct},
        "session_count": sessions,
        "compact_uses": compacts,
        "git_commits": max(0, round(sessions * persona["commit_rate"] * rng.uniform(0.5, 1.5))),
    }


# ── Simulated coaching (UPG-05) ─────────────────────────────────────────────
# Personas never change on their own, so without this there is no ground truth to check a
# "did the coaching work?" estimate against. Every COACHING_EVERY_DAYS days the critical
# engineers (bottom two by that day's score) are coached on their weakest area; with
# probability ADHERENCE they change that habit by the effect below, from the next day on.
# These sizes are simulation assumptions, not measurements of real coaching.
COACHING_EVERY_DAYS = 14
ADHERENCE = 0.7
COACHING_EFFECTS = {"none": 0.0, "small": 0.5, "moderate": 1.0}
# Habit change for an engineer who follows the "moderate" coaching.
FULL_EFFECT = {
    "cache": 0.08,         # cache hit ratio +8 points
    "model_mix": 0.15,     # 15% of usage moved from Opus to Sonnet
    "discipline": 0.25,    # /compact used in 25% more sessions
}
# area -> (persona key, direction of improvement, bound)
_HABIT = {"cache": ("cache_hit", 1, 0.95), "model_mix": ("opus_share", -1, 0.02),
          "discipline": ("compact_rate", 1, 0.95)}


def apply_coaching(persona, area, effect, rng):
    """The persona after being coached on `area` (a new dict). One adherence draw per coaching,
    whatever the effect, so changing the effect size never shifts the other random draws."""
    adhered = rng.random() < ADHERENCE
    coached = dict(persona)
    size = COACHING_EFFECTS[effect] * FULL_EFFECT[area]
    if adhered and size:
        key, sign, bound = _HABIT[area]
        value = persona[key] + sign * size
        coached[key] = min(value, bound) if sign > 0 else max(value, bound)
    return coached


def is_coaching_day(day_offset):
    """Every COACHING_EVERY_DAYS-th simulated day (day_offset counts from 0)."""
    return (day_offset + 1) % COACHING_EVERY_DAYS == 0


def flat_day(metrics):
    """Simulator metrics with the model shares flattened, the way database rows hold them."""
    flat = {k: v for k, v in metrics.items() if k != "model_mix"}
    flat.update(metrics["model_mix"])
    return flat


def select_for_coaching(history):
    """{engineer: [flat days, oldest first]} -> [(engineer, weakest area)] for the critical engineers
    on the latest day, with the same score, tier rule and weakest area the product uses."""
    def latest(days):
        return score_breakdown(days[-1], days[-POOL_DAYS:-1])["total"]

    ranked = sorted(history, key=lambda e: latest(history[e]), reverse=True)
    return [(e, coaching_facts(history[e][-1], history[e][-POOL_DAYS:-1])["weakest_area"])
            for rank, e in enumerate(ranked, start=1) if severity_for_rank(rank, len(ranked)) == CRITICAL]


# ── Injected incidents (UPG-07) ─────────────────────────────────────────────
# Known-bad days, to measure the anomaly detector against (analysis/anomaly_eval.py) and to
# show a few on the demo dashboard (--incidents). Nothing is stored about which days were
# injected: the detector only ever sees the usage numbers.
INCIDENT_KINDS = ("runaway_loop", "cache_breakage")
_TOKEN_KEYS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")


def inject_incident(metrics, kind, rng):
    """A copy of one day's metrics with an incident:
    - runaway_loop: an agent re-sends its context in a loop, so every token count is x3-6;
    - cache_breakage: the cache stops being hit (e.g. a changing prompt prefix), so the
      same prompt tokens are 5-15% cache reads and the rest uncached input."""
    day = dict(metrics)
    if kind == "runaway_loop":
        factor = rng.uniform(3, 6)
        for key in _TOKEN_KEYS:
            day[key] = int(day[key] * factor)
    elif kind == "cache_breakage":
        prompt = day["input_tokens"] + day["cache_read_tokens"] + day["cache_write_tokens"]
        day["cache_read_tokens"] = int(prompt * rng.uniform(0.05, 0.15))
        day["input_tokens"] = prompt - day["cache_read_tokens"] - day["cache_write_tokens"]
    else:
        raise ValueError(f"unknown incident kind: {kind}")
    return day


def has_usage_data():
    init_db()
    with db_session() as conn:
        return conn.execute("SELECT 1 FROM usage_metrics LIMIT 1").fetchone() is not None


def reset_data(conn):
    """Removes generated data. Alert settings are configuration, not data, so they stay."""
    for table in ("coaching_events", "coaching_guides", "usage_metrics", "engineers"):
        conn.execute(f"DELETE FROM {table}")


INCIDENT_WINDOW_DAYS = 14   # demo incidents land in the window the dashboard lists


def generate_historical_data(days_back=30, num_engineers=10, seed=DEFAULT_SEED, reset=False, end_date=None,
                             coaching_effect=None, incidents=0):
    """coaching_effect: None (no coaching) or a COACHING_EFFECTS key; see apply_coaching.
    incidents: how many incident days to inject in the last INCIDENT_WINDOW_DAYS (inject_incident)."""
    print("Ensuring database tables exist...")
    init_db()
    print(f"Generating {days_back} days of historical data for {num_engineers} engineers (seed={seed})...")

    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    engineers = make_engineers(rng, fake, num_engineers)
    personas = {eng["user_id"]: make_persona(rng) for eng in engineers}
    end_date = end_date or date.today()

    # Build the batch, then write it through the same ingestion path as POST /api/ingest:
    # same validation, server-side cost and score, idempotent upsert (re-running refreshes
    # the generated days instead of duplicating them).
    # Coaching has its own random stream, so the usage data only changes where a habit changed.
    coaching_rng = random.Random(f"coaching-{seed}")
    # Incidents too: (engineer index, day offset) -> kind, alternating kinds.
    incident_rng = random.Random(f"incidents-{seed}")
    window = range(max(0, days_back - INCIDENT_WINDOW_DAYS), days_back)
    slots = incident_rng.sample([(e, d) for e in range(num_engineers) for d in window],
                                min(incidents, num_engineers * len(window)))
    planned = {slot: INCIDENT_KINDS[i % len(INCIDENT_KINDS)] for i, slot in enumerate(slots)}
    history = {eng["user_id"]: [] for eng in engineers}
    records, events = [], []
    for day_offset in range(days_back):
        day = end_date - timedelta(days=days_back - day_offset - 1)
        for e, eng in enumerate(engineers):
            metrics = daily_metrics(rng, personas[eng["user_id"]], day)
            if (e, day_offset) in planned:
                metrics = inject_incident(metrics, planned[(e, day_offset)], incident_rng)
            history[eng["user_id"]].append(flat_day(metrics))
            mix = metrics.pop("model_mix")
            records.append(UsageRecord(user_id=eng["user_id"], date=day, name=eng["name"], email=eng["email"],
                                       **metrics, **mix))
        if coaching_effect is not None and is_coaching_day(day_offset):
            for user_id, area in select_for_coaching(history):
                personas[user_id] = apply_coaching(personas[user_id], area, coaching_effect, coaching_rng)
                events.append((user_id, day, area))

    with db_session() as conn:
        if reset:
            reset_data(conn)
        inserted, updated, rejected = upsert_usage(conn, list(enumerate(records)))
        for user_id, day, area in events:
            record_coaching(conn, user_id, day.isoformat(), CRITICAL, area, source="simulated")
    if rejected:  # the generator produced data the API would refuse: a bug, not something to skip
        raise RuntimeError(f"simulated records failed validation: {rejected[:3]}")
    print(f"Ingested {inserted} new and {updated} refreshed engineer-days.")
    if coaching_effect is not None:
        print(f"Simulated {len(events)} coaching events (true effect: {coaching_effect}).")
    if planned:
        print(f"Injected {len(planned)} incident days in the last {INCIDENT_WINDOW_DAYS} days.")
    print("Historical data successfully injected into the database!")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic DevTelemetry usage data.")
    parser.add_argument("--reset", action="store_true", help="delete existing engineers/usage/guides first")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (same seed = same data)")
    # 120 days: enough coaching rounds (every 14 days) for the coaching-impact estimate.
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--engineers", type=int, default=10)
    parser.add_argument("--if-empty", action="store_true",
                        help="do nothing if the database already has usage data (for container start)")
    parser.add_argument("--coaching-effect", choices=[*COACHING_EFFECTS, "off"], default="moderate",
                        help="true effect of the simulated coaching (UPG-05); 'off' simulates no coaching")
    parser.add_argument("--incidents", type=int, default=3,
                        help="incident days (runaway loop / broken cache) to inject in the last 14 days (UPG-07)")
    args = parser.parse_args(argv)
    if args.if_empty and has_usage_data():
        print("Database already has usage data; skipping seed.")
        return
    generate_historical_data(days_back=args.days, num_engineers=args.engineers, seed=args.seed, reset=args.reset,
                             coaching_effect=None if args.coaching_effect == "off" else args.coaching_effect,
                             incidents=args.incidents)


if __name__ == "__main__":
    main()
