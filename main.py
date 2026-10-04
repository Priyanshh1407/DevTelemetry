"""DevTelemetry daily agent (console): ranks the latest day and prints AI coaching.

Reads the same SQLite database as the dashboard (DB_PATH). If it is empty, seeds it first.
"""
import logging
import sys

from ai.guide_generator import generate_efficiency_guide, generate_team_report
from core.db import db_session, init_db
from core.queries import latest_day_rows, recent_metrics_for_user, without_pii
from core.severity import severity_for_rank
from data.seed import generate_historical_data

COACHED = 5  # how many of the lowest-ranked engineers get an individual guide


def load_latest_day():
    init_db()
    with db_session() as conn:
        engineers = latest_day_rows(conn)
    if not engineers:
        print("No usage data found. Generating synthetic telemetry...")
        generate_historical_data()
        with db_session() as conn:
            engineers = latest_day_rows(conn)
    return engineers


def main():
    engineers = load_latest_day()
    team_size = len(engineers)
    day = engineers[0]["date"]

    # Team summary for the general report
    avg_score = sum(e["efficiency_score"] for e in engineers) / team_size
    total_spend = sum(e["estimated_cost_usd"] for e in engineers)
    team_summary = {
        "team_size": team_size,
        "average_efficiency_score": round(avg_score, 2),
        "total_daily_spend_usd": round(total_spend, 2)
    }

    # Print Leaderboard
    print("\n" + "=" * 65)
    print(f"🏆 DEVTELEMETRY: EFFICIENCY LEADERBOARD — {day}")
    print("=" * 65)
    print(f"{'Rank':<5} | {'Name':<22} | {'Score':<6} | {'Spend ($)':<10}")
    print("-" * 65)
    for rank, eng in enumerate(engineers, 1):
        print(f"{rank:<5} | {eng['name']:<22} | {eng['efficiency_score']:<6.2f} | ${eng['estimated_cost_usd']:<10.2f}")

    # Team-wide report
    print("\n" + "=" * 65)
    print("📢 TEAM-WIDE OPTIMIZATION REPORT")
    print("=" * 65)
    print(generate_team_report(team_summary))

    # Individual guides for the lowest-ranked engineers
    print("\n" + "=" * 65)
    print(f"🚨 INDIVIDUAL COACHING GUIDES (BOTTOM {COACHED})")
    print("=" * 65)
    first_coached_rank = max(1, team_size - COACHED + 1)
    for rank in range(first_coached_rank, team_size + 1):
        eng = engineers[rank - 1]
        severity = severity_for_rank(rank, team_size)
        print(f"\n--- Coaching for {eng['name']} (Rank: {rank}, Score: {eng['efficiency_score']:.2f}, "
              f"Severity: {severity}) ---")
        with db_session() as conn:
            window = recent_metrics_for_user(conn, eng["user_id"])
        guide = generate_efficiency_guide(without_pii(eng), severity, recent=window[:-1])
        if guide.is_fallback:
            print(f"(fallback guide: {guide.source})")
        for n, task in enumerate(guide.tasks, 1):
            print(f"{n}. {task['desc']}")


if __name__ == "__main__":
    # Ensure stdout can print emojis on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
