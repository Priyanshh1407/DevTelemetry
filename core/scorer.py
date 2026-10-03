"""Efficiency score (0-100) for one engineer-day. Rationale and limitations: docs/scoring.md.

Token fields follow Anthropic's usage semantics: input_tokens = uncached prompt tokens,
cache_read_tokens and cache_write_tokens are separate, so a day's total prompt is their sum.

- Cache hit ratio (40 pts): cache_read / total prompt tokens
- Model mix (30 pts): Haiku 1.0, Sonnet 0.6, Opus 0.1 weights
- Session discipline (30 pts): /compact uses per session
"""

# Bump whenever the formula changes: init_db() recomputes stored scores when the version
# recorded in the database differs (see core/db.py).
SCORING_VERSION = 2

# The discipline term may look back over this many days (including the scored day).
POOL_DAYS = 7

MODEL_WEIGHTS = {"haiku_pct": 1.0, "sonnet_pct": 0.6, "opus_pct": 0.1}


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


def calculate_efficiency_score(day, recent=()):
    """Score for `day`. `recent` holds up to POOL_DAYS - 1 earlier days for the same engineer
    (oldest first); terms that pool over time use it."""
    # 1. Cache hit ratio (40 pts)
    cache_score = cache_hit_ratio(day) * 40

    # 2. Model mix (30 pts)
    mix = _model_mix(day)
    mix_ratio = sum((mix.get(key) or 0) * weight for key, weight in MODEL_WEIGHTS.items())
    model_score = mix_ratio * 30

    # 3. Session discipline (30 pts): /compact uses per session
    sessions = day["session_count"]
    compacts = day["compact_uses"]
    compact_ratio = compacts / sessions if sessions > 0 else 0
    discipline_score = min(compact_ratio, 1.0) * 30

    return round(cache_score + model_score + discipline_score, 2)


def score_history(days):
    """Scores for one engineer's days (oldest first), each with its trailing window."""
    return [calculate_efficiency_score(d, days[max(0, i - (POOL_DAYS - 1)):i]) for i, d in enumerate(days)]
