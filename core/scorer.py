"""Efficiency score (0-100) for one engineer-day. Rationale and limitations: docs/scoring.md.

Token fields follow Anthropic's usage semantics: input_tokens = uncached prompt tokens,
cache_read_tokens and cache_write_tokens are separate, so a day's total prompt is their sum.

- Cache hit ratio (40 pts): cache_read / total prompt tokens
- Model mix (30 pts): Haiku 1.0, Sonnet 0.6, Opus 0.1 weights
- Session discipline (30 pts): /compact uses per session, pooled over the last 7 days
"""

# Bump whenever the formula changes: init_db() recomputes stored scores when the version
# recorded in the database differs (see core/db.py).
SCORING_VERSION = 3  # 3: /compact term pooled over 7 days; model mix normalized

# The discipline term pools this many days (the scored day plus up to 6 before it).
POOL_DAYS = 7

MODEL_WEIGHTS = {"haiku_pct": 1.0, "sonnet_pct": 0.6, "opus_pct": 0.1}

# Maximum points per area. Judgment calls, not learned (there is no ground-truth label of an
# "efficient engineer"); analysis/weight_sensitivity.py measures how much rankings depend on them.
AREA_WEIGHTS = {"cache": 40, "model_mix": 30, "discipline": 30}


def _model_mix(day):
    """Seed/pricing code nests the shares under "model_mix"; database rows store them flat."""
    mix = day.get("model_mix")
    if mix is None:
        mix = {key: day.get(key) or 0 for key in MODEL_WEIGHTS}
    return mix


def total_prompt_tokens(day):
    return (day.get("input_tokens") or 0) + (day.get("cache_read_tokens") or 0) + (day.get("cache_write_tokens") or 0)


def cache_hit_ratio(day):
    """Share of the day's prompt tokens served from cache. Cache writes count as misses:
    they were processed in full (and then stored), not read."""
    total = total_prompt_tokens(day)
    return (day.get("cache_read_tokens") or 0) / total if total > 0 else 0.0


def score_breakdown(day, recent=(), weights=None):
    """Points per part for `day`, plus the total. `recent` holds earlier days for the same
    engineer (oldest first); only the last POOL_DAYS - 1 of them are used."""
    # 1. Cache hit ratio (40 pts)
    weights = weights or AREA_WEIGHTS
    cache_points = cache_hit_ratio(day) * weights["cache"]

    # 2. Model mix (30 pts). Shares are normalized so rounding or bad data (e.g. 0.33 x 3, or a
    #    share above 1) can't push the score past its 30 points.
    mix = _model_mix(day)
    share_total = sum((mix.get(key) or 0) for key in MODEL_WEIGHTS)
    mix_ratio = (sum((mix.get(key) or 0) * weight for key, weight in MODEL_WEIGHTS.items()) / share_total
                 if share_total > 0 else 0.0)
    model_points = mix_ratio * weights["model_mix"]

    # 3. Session discipline (30 pts): /compact uses per session, pooled over the trailing week.
    #    A single day has only a handful of sessions, so its ratio is mostly luck (0/2, 1/2, 2/2
    #    for the same habit); pooling 7 days measures the habit instead of the dice roll.
    window = list(recent)[-(POOL_DAYS - 1):] + [day] if POOL_DAYS > 1 else [day]
    sessions = sum(d.get("session_count") or 0 for d in window)
    compacts = sum(d.get("compact_uses") or 0 for d in window)
    discipline_points = min(compacts / sessions, 1.0) * weights["discipline"] if sessions > 0 else 0.0

    return {
        "cache": round(cache_points, 2),
        "model_mix": round(model_points, 2),
        "discipline": round(discipline_points, 2),
        "total": round(cache_points + model_points + discipline_points, 2),
    }


def calculate_efficiency_score(day, recent=()):
    """Score (0-100) for `day`; see score_breakdown for the parts."""
    return score_breakdown(day, recent)["total"]


def score_history(days):
    """Scores for one engineer's days (oldest first), each with its trailing window."""
    return [calculate_efficiency_score(d, days[max(0, i - (POOL_DAYS - 1)):i]) for i, d in enumerate(days)]
