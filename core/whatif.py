"""What-if savings (UPG-06): what an engineer's real usage would have cost with a better habit.

The engineer's actual tokens are re-priced with core.pricing.estimate_cost, changing one thing:

- cache lever: the same prompt tokens, re-split between uncached input and cache reads at
  the target hit ratio. Cache writes stay as they are (they were sent either way).
- model lever: Opus usage above the target share moves to Sonnet.

Targets only ever improve a habit: a day already better than the target is left alone, so a
saving is never negative. A model never estimates these numbers; they are computed here and
the coaching prompt (v3) may quote them.
"""
from statistics import quantiles

from core.pricing import estimate_cost

MAX_CACHE_HIT = 0.97     # the simulator's ceiling; some of every prompt is always new
PERIOD_DAYS = 30
SHARES = ("opus_pct", "sonnet_pct", "haiku_pct")


def _shares(day):
    raw = {k: day.get(k) or 0 for k in SHARES}
    total = sum(raw.values()) or 1
    return {k: v / total for k, v in raw.items()}


def reprice_day(day, cache_hit=None, opus_pct=None, detail=False):
    """Cost of `day` with the habits changed (None = unchanged); detail=True returns the tokens too."""
    read, write = day.get("cache_read_tokens") or 0, day.get("cache_write_tokens") or 0
    prompt = (day.get("input_tokens") or 0) + read + write
    if cache_hit is not None:
        read = max(read, min(round(cache_hit * prompt), prompt - write))
    shares = _shares(day)
    if opus_pct is not None and shares["opus_pct"] > opus_pct:
        shares["sonnet_pct"] += shares["opus_pct"] - opus_pct
        shares["opus_pct"] = opus_pct

    tokens = {"input_tokens": prompt - read - write, "output_tokens": day.get("output_tokens") or 0,
              "cache_read_tokens": read, "cache_write_tokens": write}
    cost = estimate_cost(tokens["input_tokens"], tokens["output_tokens"], read, write, shares)
    return {**tokens, **shares, "cost_usd": cost} if detail else cost


def _validate(cache_hit, opus_pct):
    if cache_hit is not None and not 0 <= cache_hit <= MAX_CACHE_HIT:
        raise ValueError(f"cache_hit must be between 0 and {MAX_CACHE_HIT}")
    if opus_pct is not None and not 0 <= opus_pct <= 1:
        raise ValueError("opus_pct must be between 0 and 1")


def what_if(days, cache_hit=None, opus_pct=None, period_days=PERIOD_DAYS):
    """Current and projected cost of `days`, scaled to `period_days`, per lever and combined."""
    _validate(cache_hit, opus_pct)
    if not days:
        raise ValueError("no usage data to re-price")
    scale = period_days / len(days)

    def month(**levers):
        return round(scale * sum(reprice_day(d, **levers) for d in days), 2)

    current = month()

    def lever(**levers):
        projected = month(**levers)
        return {"projected_month_usd": projected, "saving_month_usd": round(current - projected, 2)}

    return {"days": len(days), "period_days": period_days, "current_month_usd": current,
            "targets": {"cache_hit": cache_hit, "opus_pct": opus_pct},
            "cache": lever(cache_hit=cache_hit), "model": lever(opus_pct=opus_pct),
            "combined": lever(cache_hit=cache_hit, opus_pct=opus_pct)}


def habits(days):
    """An engineer's token-weighted cache hit ratio and Opus share over `days`."""
    prompts = [(d.get("input_tokens") or 0) + (d.get("cache_read_tokens") or 0) + (d.get("cache_write_tokens") or 0)
               for d in days]
    total = sum(prompts) or 1
    return {"cache_hit": sum(d.get("cache_read_tokens") or 0 for d in days) / total,
            "opus_pct": sum(p * _shares(d)["opus_pct"] for p, d in zip(prompts, days, strict=True)) / total}


def team_targets(team):
    """Data-driven defaults: the team's top-quartile habits (75th percentile cache hit, 25th
    percentile Opus share) over {engineer: [days]}, not invented targets."""
    per_engineer = [habits(days) for days in team.values() if days]
    if len(per_engineer) < 2:
        raise ValueError("team targets need at least two engineers")
    cache = quantiles([h["cache_hit"] for h in per_engineer], n=4, method="inclusive")[2]
    opus = quantiles([h["opus_pct"] for h in per_engineer], n=4, method="inclusive")[0]
    return {"cache_hit": round(min(cache, MAX_CACHE_HIT), 4), "opus_pct": round(opus, 4)}


def savings_facts(days, targets):
    """The savings a coaching guide may cite (rounded the way the prompt shows them)."""
    result = what_if(days, cache_hit=targets["cache_hit"], opus_pct=targets["opus_pct"])
    return {
        "window_days": len(days),
        "cache_target_pct": round(targets["cache_hit"] * 100, 1),
        "saving_month_usd_cache": result["cache"]["saving_month_usd"],
        "opus_target_pct": round(targets["opus_pct"] * 100, 1),
        "saving_month_usd_model": result["model"]["saving_month_usd"],
    }
