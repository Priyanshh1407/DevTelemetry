"""Did the coaching work? (UPG-05) Rationale and validation: docs/impact.md.

The bottom two engineers by that day's score get the critical coaching. Selecting people on
a bad day guarantees they look better afterwards even if the coaching does nothing
(regression to the mean), so "after minus the coaching day" (naive) is biased upwards.

For each coaching event (an engineer, the day they were selected, the area they were coached
on) the outcome is that area's points on single days (not the 7-day pooled /compact term),
compared over two 7-day windows:

- PRE  = days -13..-7: before the 7 days pooled into the selection day's score, so the
         baseline is not selected on bad luck either;
- POST = days +1..+7.

Both windows hold each weekday exactly once, so the weekday mix cancels.

- naive    = mean(POST) - selection day                     (kept to show the bias)
- pre_post = mean(POST) - mean(PRE)                         (biased by team-wide trends)
- did      = pre_post - the same change for engineers not coached around that day
             (difference-in-differences; assumes coached and uncoached engineers would
             have moved in parallel without the coaching)
"""
import random
from datetime import timedelta
from statistics import mean

from core.scorer import score_breakdown

AREAS = ("cache", "model_mix", "discipline")
PRE = range(-13, -6)
POST = range(1, 8)
MIN_DAYS = 5          # per window; fewer and the event is not estimated
METHODS = ("naive", "pre_post", "did")


def area_points(day, area):
    """Points in one score area for this day alone; None for a day without sessions
    (the /compact rate is undefined)."""
    if area == "discipline" and not day.get("session_count"):
        return None
    return score_breakdown(day)[area]


def _window_mean(days, start, offsets, area):
    values = [area_points(days[start + timedelta(days=k)], area) for k in offsets
              if start + timedelta(days=k) in days]
    values = [v for v in values if v is not None]
    return mean(values) if len(values) >= MIN_DAYS else None


def _coached_near(dates, day, low, high):
    return any(low <= (d - day).days <= high for d in dates)


def event_effects(series, events):
    """One row per event with before/after means and the three estimates (or why it was skipped).

    series: {user_id: {date: day metrics}}; events: [{"user_id", "coached_on" (date), "target_area"}].
    """
    coached = {}
    for e in events:
        coached.setdefault(e["user_id"], []).append(e["coached_on"])

    rows = []
    for e in events:
        user, day, area = e["user_id"], e["coached_on"], e["target_area"]
        row = {"user_id": user, "coached_on": day, "target_area": area, "status": "included",
               "before": None, "selection_day": None, "after": None, "control_change": None,
               "n_controls": 0, "naive": None, "pre_post": None, "did": None}
        rows.append(row)

        # Another coaching of the same engineer whose effect would land in either window.
        others = [d for d in coached[user] if d != day]
        if _coached_near(others, day, PRE.start, -1) or _coached_near(others, day, 1, POST.stop - 2):
            row["status"] = "overlapping coaching"
            continue

        days = series.get(user, {})
        before = _window_mean(days, day, PRE, area)
        after = _window_mean(days, day, POST, area)
        selection = area_points(days[day], area) if day in days else None
        if before is None or after is None or selection is None:
            row["status"] = "insufficient data"
            continue

        changes = []
        for other, other_days in series.items():
            if other == user or _coached_near(coached.get(other, []), day, PRE.start, POST.stop - 2):
                continue
            c_before = _window_mean(other_days, day, PRE, area)
            c_after = _window_mean(other_days, day, POST, area)
            if c_before is not None and c_after is not None:
                changes.append(c_after - c_before)
        if not changes:
            row["status"] = "no comparison group"
            continue

        control_change = mean(changes)
        row.update(before=round(before, 3), selection_day=selection, after=round(after, 3),
                   control_change=round(control_change, 3), n_controls=len(changes),
                   naive=round(after - selection, 3), pre_post=round(after - before, 3),
                   did=round(after - before - control_change, 3))
    return rows


def summarize(rows, n_boot=1000, seed=0):
    """Mean of each estimate over the included events, with a 95% bootstrap interval.

    Events on the same day share their comparison group, so whole coaching days are resampled
    (a cluster bootstrap). With fewer than two coaching days there is no interval."""
    included = [r for r in rows if r["status"] == "included"]
    clusters = {}
    for r in included:
        clusters.setdefault(r["coached_on"], []).append(r)
    groups = list(clusters.values())
    rng = random.Random(seed)
    resamples = [[rng.randrange(len(groups)) for _ in groups] for _ in range(n_boot)] if len(groups) >= 2 else []
    sizes = [len(g) for g in groups]

    summary = {"n_events": len(included), "n_excluded": len(rows) - len(included), "n_days": len(groups)}
    for method in METHODS:
        estimate = round(mean(r[method] for r in included), 3) if included else None
        low = high = None
        if resamples:
            sums = [sum(r[method] for r in g) for g in groups]
            boots = sorted(sum(sums[i] for i in pick) / sum(sizes[i] for i in pick) for pick in resamples)
            low, high = round(boots[int(0.025 * n_boot)], 3), round(boots[int(0.975 * n_boot) - 1], 3)
        summary[method] = {"estimate": estimate, "ci_low": low, "ci_high": high}
    return summary
