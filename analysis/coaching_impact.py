"""Does core/impact.py measure the effect of coaching correctly? (UPG-05)

Real coaching has no answer key, so this checks the estimators where the answer is known:
simulated teams (the persona model in data/seed.py, in memory) are coached every 14 days
exactly like the product does it (the critical engineers, on their weakest area), with a
true effect of zero or "moderate". A team-wide drift in caching (as after a tooling update)
runs in the background, because real teams don't stand still either.

Every engineer-day draws its noise from its own seeded random stream, so each coached day
can be regenerated with the habit the engineer had before the coaching: the difference is
the exact effect of that coaching on that day (a coupled counterfactual). Averaged over
days +1..+7 and over a team's events, that is the truth each estimate is compared with.

    python -m analysis.coaching_impact
"""
import random
from datetime import date, timedelta
from statistics import mean

from core.impact import METHODS, POST, area_points, event_effects, summarize
from data.seed import apply_coaching, daily_metrics, flat_day, is_coaching_day, make_persona, select_for_coaching

DAYS = 168                 # 24 weeks: 12 coaching rounds
TEAM_DRIFT = 0.002         # cache hit ratio gained by everyone per day (+0.8 points of score a week)
START = date(2026, 1, 5)   # a Monday


def _day(seed, engineer, offset, persona):
    """One engineer-day from its own random stream: the same inputs always give the same day."""
    rng = random.Random(f"{seed}:{engineer}:{offset}")
    drifted = {**persona, "cache_hit": min(0.95, persona["cache_hit"] + TEAM_DRIFT * offset)}
    return flat_day(daily_metrics(rng, drifted, START + timedelta(days=offset)))


def simulate_team(seed, effect, engineers=10, days=DAYS):
    """(series, events, truth): truth[(engineer, day)] = the event's true mean effect over POST."""
    personas = {f"e{e}": make_persona(random.Random(f"{seed}:persona:{e}")) for e in range(engineers)}
    coaching_rng = random.Random(f"{seed}:coaching")
    history = {e: [] for e in personas}
    series = {e: {} for e in personas}
    events, truth, before = [], {}, {}

    for offset in range(days):
        day = START + timedelta(days=offset)
        for e, persona in personas.items():
            metrics = _day(seed, e, offset, persona)
            history[e].append(metrics)
            series[e][day] = metrics
        if is_coaching_day(offset):
            for e, area in select_for_coaching(history):
                before[(e, day)] = personas[e]
                personas[e] = apply_coaching(personas[e], area, effect, coaching_rng)
                events.append({"user_id": e, "coached_on": day, "target_area": area, "offset": offset})

    for ev in events:
        e, day, area, offset = ev["user_id"], ev["coached_on"], ev["target_area"], ev["offset"]
        after = personas_after = None
        diffs = []
        for k in POST:
            if offset + k >= days:
                break
            actual = series[e][day + timedelta(days=k)]
            without = _day(seed, e, offset + k, before[(e, day)])
            after, personas_after = area_points(actual, area), area_points(without, area)
            diffs.append(after - personas_after)
        truth[(e, day)] = mean(diffs) if diffs else None
    return series, events, truth


def evaluate_team(seed, effect):
    """(summary, true effect, included event rows each with its own "truth")."""
    series, events, truth = simulate_team(seed, effect)
    rows = event_effects(series, events)
    included = [{**r, "truth": truth[(r["user_id"], r["coached_on"])]} for r in rows if r["status"] == "included"]
    true_effect = mean(r["truth"] for r in included) if included else None
    return summarize(rows), true_effect, included


def run(teams=200, effects=("none", "moderate")):
    results = {}
    for effect in effects:
        evaluated = [evaluate_team(seed, effect) for seed in range(1, teams + 1)]
        per_team = [(s, t) for s, t, _ in evaluated if t is not None and s["did"]["ci_low"] is not None]
        truths = [t for _, t in per_team]
        # The team-wide drift only moves caching, so a trend bias can only show on these events.
        cache_events = [r for _, _, rows in evaluated for r in rows if r["target_area"] == "cache"]
        stats = {"teams": len(per_team), "true_effect": mean(truths),
                 "events_per_team": mean(s["n_events"] for s, _ in per_team),
                 "excluded_per_team": mean(s["n_excluded"] for s, _ in per_team),
                 "cache_events": len(cache_events),
                 "all_events": sum(len(rows) for _, _, rows in evaluated),
                 "cache_bias": {m: (mean(r[m] - r["truth"] for r in cache_events) if cache_events else None)
                                for m in METHODS}}
        for method in METHODS:
            estimates = [s[method]["estimate"] for s, _ in per_team]
            covered = [s[method]["ci_low"] <= t <= s[method]["ci_high"] for s, t in per_team]
            claims = [s[method]["ci_low"] > 0 for s, _ in per_team]
            stats[method] = {"mean_estimate": mean(estimates), "bias": mean(estimates) - mean(truths),
                             "coverage": mean(covered), "claims_effect": mean(claims)}
        results[effect] = stats
    return results


NAMES = {"naive": "Naive (after - coaching day)", "pre_post": "Before/after (clean baseline)",
         "did": "Difference-in-differences"}


def report(results):
    lines = []
    for effect, s in results.items():
        lines += [f"### True effect: {effect} ({s['teams']} simulated teams of 10, {DAYS} days each)", "",
                  f"Mean true effect: {s['true_effect']:+.2f} points in the coached area. "
                  f"Events per team: {s['events_per_team']:.1f} estimated, {s['excluded_per_team']:.1f} excluded.", "",
                  "| Method | Mean estimate | Bias | 95% CI covers the truth | Teams where the CI says \"it worked\" |",
                  "|---|---|---|---|---|"]
        for method in METHODS:
            m = s[method]
            lines.append(f"| {NAMES[method]} | {m['mean_estimate']:+.2f} | {m['bias']:+.2f} | "
                         f"{m['coverage'] * 100:.0f}% | {m['claims_effect'] * 100:.0f}% |")
        bias = s["cache_bias"]
        if bias["did"] is not None:
            lines += ["", f"Cache-coached events only ({s['cache_events']} of {s['all_events']}; the team-wide "
                      "caching drift acts here): bias per event " +
                      ", ".join(f"{NAMES[m].split(' (')[0].lower()} {bias[m]:+.2f}" for m in METHODS) + "."]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(run()))  # noqa: T201
