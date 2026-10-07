"""How good is the spend-anomaly detector? (UPG-07)

Simulated teams (the persona model in data/seed.py, in memory) get known incidents injected
at random: runaway agent loops (every token x3-6) and broken caching (hit ratio 5-15%), about
one per engineer per month. Three detectors then look at the daily costs, without knowing
where the incidents are:

- robust:      core/anomaly.py (median/MAD of the engineer's own same-day-type history);
- fixed $30:   one team-wide threshold ("below $30 per active day for 90% of users");
- mean + 3 sd: the textbook rule, on the same baseline windows and the same $ floor as the
               robust detector, so the only difference is the statistic.

    python -m analysis.anomaly_eval
"""
import random
from datetime import date, timedelta
from statistics import mean, pstdev

from core.anomaly import BASELINE_DAYS, MIN_EXCESS_USD, day_cost, day_type, detect
from data.seed import INCIDENT_KINDS, daily_metrics, flat_day, inject_incident, make_persona

DAYS = 120
INCIDENT_RATE = 1 / 30        # per engineer-day (about one per engineer-month)
FIXED_THRESHOLD_USD = 30.0
START = date(2026, 1, 5)
DETECTORS = ("robust", "fixed", "mean_sd")


def simulate_team(seed, engineers=10, days=DAYS):
    """{engineer: [flat days]} and {(engineer, day index): incident kind}."""
    rng = random.Random(seed)
    incident_rng = random.Random(f"{seed}:incidents")
    team, incidents = {}, {}
    for e in range(engineers):
        persona = make_persona(rng)
        series = []
        for i in range(days):
            day = flat_day(daily_metrics(rng, persona, START + timedelta(days=i)))
            if incident_rng.random() < INCIDENT_RATE:
                kind = incident_rng.choice(INCIDENT_KINDS)
                day = inject_incident(day, kind, incident_rng)
                incidents[(e, i)] = kind
            series.append({**day, "date": START + timedelta(days=i)})
        team[e] = series
    return team, incidents


def _baseline(series, costs, i):
    d = series[i]["date"]
    return [costs[j] for j in range(i) if (d - series[j]["date"]).days <= BASELINE_DAYS
            and day_type(series[j]["date"]) == day_type(d)]


def flags(series):
    """{detector: [flagged? per day]} for one engineer."""
    costs = [day_cost(d) for d in series]
    robust = [r["flagged"] for r in detect(series)]
    fixed = [c > FIXED_THRESHOLD_USD for c in costs]
    mean_sd = []
    for i, c in enumerate(costs):
        base = _baseline(series, costs, i)
        m = mean(base) if base else None
        mean_sd.append(bool(base) and len(base) >= 8 and c > m + 3 * pstdev(base) and c - m >= MIN_EXCESS_USD)
    return {"robust": robust, "fixed": fixed, "mean_sd": mean_sd}


def evaluate(teams=200, days=DAYS):
    counts = {d: {"tp": 0, "fp": 0, "fn": 0} for d in DETECTORS}
    by_kind = {d: {k: [0, 0] for k in (*INCIDENT_KINDS, "weekend")} for d in DETECTORS}   # [caught, total]
    engineer_days = 0
    for seed in range(1, teams + 1):
        team, incidents = simulate_team(seed, days=days)
        for e, series in team.items():
            flagged = flags(series)
            for i in range(BASELINE_DAYS, days):     # every detector judged on the same days
                engineer_days += 1
                kind = incidents.get((e, i))
                weekend = day_type(series[i]["date"]) == "weekend"
                for d in DETECTORS:
                    hit = flagged[d][i]
                    if kind:
                        counts[d]["tp" if hit else "fn"] += 1
                        for key in (kind, "weekend") if weekend else (kind,):
                            by_kind[d][key][0] += hit
                            by_kind[d][key][1] += 1
                    elif hit:
                        counts[d]["fp"] += 1
    months = engineer_days / 30
    results = {}
    for d in DETECTORS:
        tp, fp, fn = counts[d]["tp"], counts[d]["fp"], counts[d]["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        results[d] = {"precision": precision, "recall": recall,
                      "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                      "false_alarms_per_engineer_month": fp / months,
                      "recall_by": {k: (c / n if n else None) for k, (c, n) in by_kind[d].items()}}
    return {"teams": teams, "engineer_days": engineer_days,
            "incidents": counts["robust"]["tp"] + counts["robust"]["fn"], "detectors": results}


NAMES = {"robust": "Robust (median/MAD, own same-type days)", "fixed": f"Fixed ${FIXED_THRESHOLD_USD:.0f}/day",
         "mean_sd": "Mean + 3 sd (same windows and $ floor)"}


def report(r):
    lines = [f"{r['teams']} simulated teams of 10, {r['engineer_days']} engineer-days judged, "
             f"{r['incidents']} injected incidents", "",
             "| Detector | Precision | Recall | F1 | False alarms per engineer-month | Recall: runaway loop | "
             "Recall: broken cache | Recall: weekend incidents |", "|---|---|---|---|---|---|---|---|"]
    for d in DETECTORS:
        m = r["detectors"][d]
        by = m["recall_by"]
        lines.append(f"| {NAMES[d]} | {m['precision'] * 100:.0f}% | {m['recall'] * 100:.0f}% | {m['f1']:.2f} | "
                     f"{m['false_alarms_per_engineer_month']:.2f} | {by['runaway_loop'] * 100:.0f}% | "
                     f"{by['cache_breakage'] * 100:.0f}% | {by['weekend'] * 100:.0f}% |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(evaluate()))  # noqa: T201
