"""Spend anomalies (UPG-07): a day that costs far more than this engineer's own normal.

A runaway agent loop or broken prompt caching shows up only as a bigger bill. One fixed
threshold can't catch it: $30 is a normal Monday for a heavy user and an alarming one for
a light user. So each day is compared with the same engineer's previous BASELINE_DAYS days
of the same type (weekdays with weekdays, weekends with weekends, so a quiet Saturday is
never "unusual"), using the median and the median absolute deviation (MAD). One earlier
incident in the baseline barely moves those; it would inflate a mean and standard deviation.

A day is flagged when both hold:
- robust z = 0.6745 * (cost - median) / MAD >= Z_THRESHOLD (unusual for this person), and
- cost - median >= MIN_EXCESS_USD (worth someone's attention).

The driver is the habit that explains most of the excess, found by re-pricing the day with
the engineer's normal habit (core.whatif.reprice_day): cache (caching broke: more uncached
input), model_mix (more Opus) or volume (more tokens, e.g. a runaway loop).
Evaluated on injected incidents in analysis/anomaly_eval.py; see docs/anomalies.md.
"""
from datetime import date, timedelta
from statistics import median

from core.scorer import cache_hit_ratio, total_prompt_tokens
from core.whatif import reprice_day

BASELINE_DAYS = 28
MIN_BASELINE = 8          # weekends: 28 days hold exactly 8
Z_THRESHOLD = 3.5         # the usual cut-off for the modified z-score (Iglewicz & Hoaglin)
MIN_EXCESS_USD = 5.0
MAD_FLOOR_USD = 0.25      # a perfectly regular history (MAD 0) must not flag every cent
DRIVERS = {"cache": "caching broke (more uncached input)", "model_mix": "more Opus",
           "volume": "more tokens (e.g. a runaway agent loop)"}


def _date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def day_type(d):
    return "weekend" if d.weekday() >= 5 else "weekday"


def day_cost(day):
    """The stored cost when there is one (what the dashboard shows), else priced from the tokens."""
    if day.get("estimated_cost_usd") is not None:
        return day["estimated_cost_usd"]
    return reprice_day(day)


def _opus_share(day):
    total = sum(day.get(k) or 0 for k in ("opus_pct", "sonnet_pct", "haiku_pct")) or 1
    return (day.get("opus_pct") or 0) / total


def driver(day, baseline):
    """Which habit explains most of the day's extra cost, versus the engineer's normal."""
    cost = reprice_day(day)
    normal_prompt = median(total_prompt_tokens(d) for d in baseline)
    prompt = total_prompt_tokens(day)
    contributions = {
        # Same day with the usual cache hit ratio (only ever restores a lower one).
        "cache": cost - reprice_day(day, cache_hit=min(median(cache_hit_ratio(d) for d in baseline), 0.97)),
        # Same day with the usual Opus share (only ever lowers a higher one).
        "model_mix": cost - reprice_day(day, opus_pct=median(_opus_share(d) for d in baseline)),
        # Same habits, usual volume.
        "volume": cost * (1 - normal_prompt / prompt) if prompt > normal_prompt else 0.0,
    }
    return max(contributions, key=contributions.get)


def detect(days):
    """One result per day (in date order) for one engineer's usage rows."""
    ordered = sorted(days, key=lambda d: _date(d["date"]))
    dates = [_date(d["date"]) for d in ordered]
    costs = [day_cost(d) for d in ordered]
    results = []
    for i, (d, cost) in enumerate(zip(dates, costs, strict=True)):
        start = d - timedelta(days=BASELINE_DAYS)
        same_type = [j for j in range(i) if start <= dates[j] < d and day_type(dates[j]) == day_type(d)]
        result = {"date": ordered[i]["date"], "cost_usd": round(cost, 2), "evaluated": False, "flagged": False,
                  "baseline_median_usd": None, "z": None, "excess_usd": None, "driver": None}
        results.append(result)
        if len(same_type) < MIN_BASELINE:
            continue
        base = [costs[j] for j in same_type]
        med = median(base)
        mad = max(median(abs(c - med) for c in base), MAD_FLOOR_USD)
        z = 0.6745 * (cost - med) / mad
        excess = cost - med
        flagged = z >= Z_THRESHOLD and excess >= MIN_EXCESS_USD
        result.update(evaluated=True, flagged=flagged, baseline_median_usd=round(med, 2), z=round(z, 2),
                      excess_usd=round(excess, 2),
                      driver=driver(ordered[i], [ordered[j] for j in same_type]) if flagged else None)
    return results


def recent_anomalies(team, days, names=None):
    """Flagged days in the last `days` days (up to the latest date in `team`), most recent and
    largest first. team: {user_id: rows covering at least days + BASELINE_DAYS}."""
    dates = [_date(r["date"]) for rows in team.values() for r in rows]
    if not dates:
        return []
    since = max(dates) - timedelta(days=days)
    found = []
    for user_id, rows in team.items():
        for result in detect(rows):
            if result["flagged"] and _date(result["date"]) > since:
                found.append({"user_id": user_id, "name": (names or {}).get(user_id), **result,
                              "date": _date(result["date"]).isoformat(),
                              "driver_label": DRIVERS[result["driver"]]})
    return sorted(found, key=lambda a: (a["date"], a["excess_usd"]), reverse=True)
