"""The facts a coaching guide may cite.

These numbers are computed here, once, from the engineer's data. The prompt gives them to
the model, the rule-based fallback writes from them, and the eval harness checks the
model's output against them (any other number in a guide counts as ungrounded).
Identity (name, email) is never part of the facts.
"""
from core.scorer import POOL_DAYS, cache_hit_ratio, score_breakdown, total_prompt_tokens

MAX_POINTS = {"cache": 40, "model_mix": 30, "discipline": 30}
AREA_LABELS = {"cache": "prompt caching", "model_mix": "model choice", "discipline": "context management (/compact)"}


def _pct(value):
    return round(value * 100, 1)


def coaching_facts(day, recent=(), savings=None):
    """Facts for one engineer-day; `recent` = earlier days (oldest first) for the 7-day terms.
    `savings` (core.whatif.savings_facts), when given, is added for prompt v3."""
    points = score_breakdown(day, recent)
    window = list(recent)[-(POOL_DAYS - 1):] + [day]
    sessions = sum(d.get("session_count") or 0 for d in window)
    compacts = sum(d.get("compact_uses") or 0 for d in window)

    shares = {key: day.get(key) or 0 for key in ("opus_pct", "sonnet_pct", "haiku_pct")}
    share_total = sum(shares.values()) or 1
    points_lost = {area: round(MAX_POINTS[area] - points[area], 2) for area in MAX_POINTS}

    return {
        "date": day.get("date"),
        "efficiency_score": points["total"],
        "points": {area: points[area] for area in MAX_POINTS},
        "points_lost": points_lost,
        "weakest_area": max(points_lost, key=points_lost.get),
        "cache_hit_pct": _pct(cache_hit_ratio(day)),
        "opus_pct": _pct(shares["opus_pct"] / share_total),
        "sonnet_pct": _pct(shares["sonnet_pct"] / share_total),
        "haiku_pct": _pct(shares["haiku_pct"] / share_total),
        "sessions_7d": sessions,
        "compacts_7d": compacts,
        "compact_rate_7d_pct": _pct(compacts / sessions) if sessions else 0.0,
        "cost_usd": round(day.get("estimated_cost_usd") or 0, 2),
        "prompt_tokens": total_prompt_tokens(day),
        "output_tokens": day.get("output_tokens") or 0,
        **({"savings": savings} if savings else {}),
    }
