"""Rule-based coaching guide, used when the model is unavailable, rate-limited or keeps
returning invalid output. Deterministic, built only from the engineer's facts, and ordered
by points lost, so it still targets the weakest area first."""
from ai.features import AREA_LABELS


def _saving(f, key, target_key, habit):
    """A computed saving (UPG-06) as a sentence, or "" when there is none to quote."""
    savings = f.get("savings") or {}
    if savings.get(key, 0) <= 0:
        return ""
    return (f" Reaching the team's top-quartile {habit} ({savings[target_key]}%) would save "
            f"${savings[key]:.2f} per 30 days.")


def _cache_action(f):
    return {
        "title": "Reuse cached context",
        "problem": f"Only {f['cache_hit_pct']}% of your prompt tokens were served from cache."
                   + _saving(f, "saving_month_usd_cache", "cache_target_pct", "cache hit ratio"),
        "fix": "Stay in one session per task and keep CLAUDE.md and project context stable, so "
               "repeated context is read from cache instead of being re-sent.",
        "focus": "cache",
    }


def _model_action(f):
    return {
        "title": "Match the model to the task",
        "problem": f"Opus handled {f['opus_pct']}% of your usage (Sonnet {f['sonnet_pct']}%, "
                   f"Haiku {f['haiku_pct']}%)."
                   + _saving(f, "saving_month_usd_model", "opus_target_pct", "Opus share"),
        "fix": "Default to Sonnet, use Haiku for tests, docs and small edits, and switch to Opus only "
               "for hard design problems (/model).",
        "focus": "model_mix",
    }


def _discipline_action(f):
    return {
        "title": "Compact long sessions",
        "problem": f"You used /compact in {f['compact_rate_7d_pct']}% of sessions over the last 7 days "
                   f"({f['compacts_7d']} of {f['sessions_7d']}).",
        "fix": "Run /compact between sub-tasks and before switching topics, so each request "
               "re-sends less history.",
        "focus": "discipline",
    }


_BUILDERS = {"cache": _cache_action, "model_mix": _model_action, "discipline": _discipline_action}


def rule_based_guide(facts):
    ordered = sorted(facts["points_lost"], key=facts["points_lost"].get, reverse=True)
    return {
        "headline": f"Your biggest opportunity is {AREA_LABELS[ordered[0]]}.",
        "actions": [_BUILDERS[area](facts) for area in ordered],
    }
