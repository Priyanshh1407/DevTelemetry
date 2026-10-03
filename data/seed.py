"""Synthetic telemetry generator.

Usage:
    python data/seed.py                 # add data (idempotent: same engineers, existing days kept)
    python data/seed.py --reset         # wipe engineers/usage/guides first (keeps alert settings)
    python data/seed.py --seed 7 --days 60 --engineers 12
    python data/seed.py --if-empty      # container start: seed only a fresh database
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

from core.db import db_session, init_db
from core.scorer import calculate_efficiency_score
from core.pricing import estimate_cost

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

    return {
        "input_tokens": prompt_tokens,  # includes cache reads (see core/pricing.py assumptions)
        "output_tokens": int(prompt_tokens * persona["output_ratio"] * rng.uniform(0.8, 1.2)),
        "cache_read_tokens": int(prompt_tokens * cache_hit),
        "cache_write_tokens": int(prompt_tokens * persona["write_ratio"] * rng.uniform(0.8, 1.2)),
        "model_mix": {"opus_pct": opus_pct, "sonnet_pct": sonnet_pct, "haiku_pct": haiku_pct},
        "session_count": sessions,
        "compact_uses": compacts,
        "git_commits": max(0, round(sessions * persona["commit_rate"] * rng.uniform(0.5, 1.5))),
    }


def has_usage_data():
    init_db()
    with db_session() as conn:
        return conn.execute("SELECT 1 FROM usage_metrics LIMIT 1").fetchone() is not None


def reset_data(conn):
    """Removes generated data. Alert settings are configuration, not data, so they stay."""
    for table in ("ai_guides", "usage_metrics", "engineers"):
        conn.execute(f"DELETE FROM {table}")


def generate_historical_data(days_back=30, num_engineers=10, seed=DEFAULT_SEED, reset=False, end_date=None):
    print("Ensuring database tables exist...")
    init_db()
    print(f"Generating {days_back} days of historical data for {num_engineers} engineers (seed={seed})...")

    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)
    engineers = make_engineers(rng, fake, num_engineers)
    personas = {eng["user_id"]: make_persona(rng) for eng in engineers}
    end_date = end_date or date.today()

    with db_session() as conn:
        if reset:
            reset_data(conn)

        for eng in engineers:
            conn.execute(
                "INSERT OR IGNORE INTO engineers (user_id, name, email) VALUES (?, ?, ?)",
                (eng["user_id"], eng["name"], eng["email"])
            )

        for day_offset in range(days_back):
            day = end_date - timedelta(days=days_back - day_offset - 1)
            current_date = day.isoformat()

            for eng in engineers:
                metrics = daily_metrics(rng, personas[eng["user_id"]], day)
                # Cost is derived from the usage above (was random.uniform(5, 30), unrelated to tokens)
                metrics["estimated_cost_usd"] = round(estimate_cost(
                    input_tokens=metrics["input_tokens"],
                    output_tokens=metrics["output_tokens"],
                    cache_read_tokens=metrics["cache_read_tokens"],
                    cache_write_tokens=metrics["cache_write_tokens"],
                    model_mix=metrics["model_mix"],
                ), 4)
                efficiency_score = calculate_efficiency_score(metrics)
                mix = metrics["model_mix"]

                # INSERT OR IGNORE + UNIQUE(user_id, date): existing days are kept, so a re-run is a no-op
                conn.execute("""
                    INSERT OR IGNORE INTO usage_metrics
                    (user_id, date, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    opus_pct, sonnet_pct, haiku_pct, session_count, compact_uses, git_commits,
                    estimated_cost_usd, efficiency_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    eng["user_id"], current_date, metrics["input_tokens"], metrics["output_tokens"],
                    metrics["cache_read_tokens"], metrics["cache_write_tokens"],
                    mix["opus_pct"], mix["sonnet_pct"], mix["haiku_pct"],
                    metrics["session_count"], metrics["compact_uses"], metrics["git_commits"],
                    metrics["estimated_cost_usd"], efficiency_score
                ))

        conn.commit()
    print("Historical data successfully injected into the database!")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate synthetic DevTelemetry usage data.")
    parser.add_argument("--reset", action="store_true", help="delete existing engineers/usage/guides first")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (same seed = same data)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--engineers", type=int, default=10)
    parser.add_argument("--if-empty", action="store_true",
                        help="do nothing if the database already has usage data (for container start)")
    args = parser.parse_args(argv)
    if args.if_empty and has_usage_data():
        print("Database already has usage data; skipping seed.")
        return
    generate_historical_data(days_back=args.days, num_engineers=args.engineers, seed=args.seed, reset=args.reset)


if __name__ == "__main__":
    main()
