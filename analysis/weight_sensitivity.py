"""How much does the leaderboard depend on the score weights? (UPG-03)

The area weights (cache 40, model mix 30, /compact 30) are judgment calls. This analysis
simulates teams with the persona generator (data/seed.py, in memory, no database), ranks the
latest day with the real weights, then re-ranks with each weight moved by +/-20% and reports:

- Kendall tau between the two rankings (1.0 = identical order, 0 = unrelated);
- how often the bottom two (who get "critical" alerts) stay the same.

    python -m analysis.weight_sensitivity
"""
import random
from datetime import date, timedelta
from statistics import mean

from core.scorer import AREA_WEIGHTS, POOL_DAYS, score_breakdown
from data.seed import daily_metrics, make_persona

CHANGES = (0.8, 1.2)


def kendall_tau(order_a, order_b):
    """Kendall tau-a between two rankings of the same items (lists, best first)."""
    pos_b = {item: i for i, item in enumerate(order_b)}
    n = len(order_a)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if pos_b[order_a[i]] < pos_b[order_a[j]]:
                concordant += 1
            else:
                discordant += 1
    pairs = n * (n - 1) / 2
    return (concordant - discordant) / pairs if pairs else 1.0


def simulate_team(seed, engineers=10, days=30, end=date(2026, 3, 31)):
    """{engineer: [day metrics, oldest first]} from the persona model, without a database."""
    rng = random.Random(seed)
    personas = [make_persona(rng) for _ in range(engineers)]
    team = {}
    for e, persona in enumerate(personas):
        team[f"e{e}"] = [daily_metrics(rng, persona, end - timedelta(days=days - 1 - d)) for d in range(days)]
    return team


def ranking(team, weights):
    def latest_score(days):
        return score_breakdown(days[-1], days[-POOL_DAYS:-1], weights=weights)["total"]
    return sorted(team, key=lambda e: latest_score(team[e]), reverse=True)


def variants():
    yield "baseline (40/30/30)", dict(AREA_WEIGHTS)
    for area in AREA_WEIGHTS:
        for change in CHANGES:
            weights = dict(AREA_WEIGHTS)
            weights[area] = AREA_WEIGHTS[area] * change
            yield f"{area} {'+' if change > 1 else '-'}20% ({weights[area]:g})", weights


def run(seeds=range(1, 31)):
    teams = [simulate_team(seed) for seed in seeds]
    baselines = [ranking(team, AREA_WEIGHTS) for team in teams]
    results = []
    for name, weights in variants():
        taus, same_bottom2 = [], []
        for team, base in zip(teams, baselines, strict=True):
            order = ranking(team, weights)
            taus.append(kendall_tau(base, order))
            same_bottom2.append(set(order[-2:]) == set(base[-2:]))
        results.append({"variant": name, "mean_tau": round(mean(taus), 3), "min_tau": round(min(taus), 3),
                        "bottom2_unchanged": round(sum(same_bottom2) / len(same_bottom2), 3)})
    return results


def report(results, teams):
    lines = [f"Weight sensitivity over {teams} simulated teams of 10 (latest-day ranking)", "",
             "| Weights | Mean Kendall tau | Worst team | Bottom 2 unchanged |", "|---|---|---|---|"]
    lines += [f"| {r['variant']} | {r['mean_tau']:.3f} | {r['min_tau']:.3f} | {r['bottom2_unchanged'] * 100:.0f}% |"
              for r in results]
    return "\n".join(lines)


if __name__ == "__main__":
    seeds = range(1, 31)
    print(report(run(seeds), len(seeds)))  # noqa: T201
