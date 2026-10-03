"""Synthetic telemetry generator.

Usage:
    python data/seed.py                 # add data (idempotent: same engineers, existing days kept)
    python data/seed.py --reset         # wipe engineers/usage/guides first (keeps alert settings)
    python data/seed.py --seed 7 --days 60 --engineers 12
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

from core.db import get_db_connection, init_db
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


def daily_metrics(rng):
    """One engineer-day of usage."""
    input_tokens = rng.randint(50000, 400000)
    cache_read_tokens = rng.randint(0, int(input_tokens * 0.9))

    # Model mix generation
    opus_raw = rng.uniform(0.0, 0.4)
    sonnet_raw = rng.uniform(0.3, 0.8)
    haiku_raw = rng.uniform(0.1, 0.5)
    total = opus_raw + sonnet_raw + haiku_raw
    opus_pct = round(opus_raw / total, 2)
    sonnet_pct = round(sonnet_raw / total, 2)
    haiku_pct = round(1.0 - opus_pct - sonnet_pct, 2)

    return {
        "input_tokens": input_tokens,
        "output_tokens": rng.randint(10000, 80000),
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": rng.randint(5000, 50000),
        "model_mix": {"opus_pct": opus_pct, "sonnet_pct": sonnet_pct, "haiku_pct": haiku_pct},
        "session_count": rng.randint(1, 8),
        "compact_uses": rng.randint(0, 5),
        "git_commits": rng.randint(0, 12),
    }


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
    end_date = end_date or date.today()

    with get_db_connection() as conn:
        if reset:
            reset_data(conn)

        for eng in engineers:
            conn.execute(
                "INSERT OR IGNORE INTO engineers (user_id, name, email) VALUES (?, ?, ?)",
                (eng["user_id"], eng["name"], eng["email"])
            )

        for day_offset in range(days_back):
            current_date = (end_date - timedelta(days=days_back - day_offset - 1)).isoformat()

            for eng in engineers:
                metrics = daily_metrics(rng)
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
    args = parser.parse_args(argv)
    generate_historical_data(days_back=args.days, num_engineers=args.engineers, seed=args.seed, reset=args.reset)


if __name__ == "__main__":
    main()
