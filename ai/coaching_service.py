"""Coaching guides for API and CLI callers: stored guides first, generation otherwise, and every
request metered. The generator itself stays free of database code."""
import logging
from dataclasses import dataclass

from ai.guide_generator import GuideResult, generate_efficiency_guide, tasks_from_guide
from ai.prompts import PROMPT_VERSION, PROMPT_VERSION_V3
from ai.providers import get_provider
from ai.store import load_guide, record_request, save_guide
from core.db import db_session
from core.queries import latest_metrics_for_user, recent_days_by_engineer, recent_metrics_for_user, without_pii
from core.whatif import savings_facts, team_targets

logger = logging.getLogger(__name__)


def _savings(conn, user_id):
    """Computed savings for prompt v3 (UPG-06): the engineer's last 30 days re-priced at the
    team's top-quartile habits. None without a team to compare with."""
    team = recent_days_by_engineer(conn)
    if len(team) < 2 or not team.get(user_id):
        return None
    return savings_facts(team[user_id], team_targets(team))


@dataclass
class Coaching:
    latest: dict          # the engineer's latest day (with name; never sent to the LLM)
    result: GuideResult
    cached: bool


def get_coaching(user_id, severity):
    """The coaching guide for an engineer's latest day, or None if they have no data."""
    provider = get_provider()
    # A guide from the fallback model is stored under that model's name; reuse it rather than
    # call again, but prefer one from the main model.
    models = [provider.model] + [m for m in [getattr(provider, "fallback_model", None)] if m]
    with db_session() as conn:
        latest = latest_metrics_for_user(conn, user_id)
        if latest is None:
            return None
        window = recent_metrics_for_user(conn, user_id)
        savings = _savings(conn, user_id) if PROMPT_VERSION == PROMPT_VERSION_V3 else None
        stored, model = None, provider.model
        for candidate in models:
            stored = load_guide(conn, user_id, latest["date"], severity, PROMPT_VERSION, candidate)
            if stored is not None:
                model = candidate
                break
        if stored is not None:
            logger.info("Coaching guide served from the store for %s", user_id)
            record_request(conn, "guide", "cache_hit", user_id=user_id, model=model, prompt_version=PROMPT_VERSION)
            result = GuideResult(tasks=tasks_from_guide(stored), source="ai", guide=stored,
                                 prompt_version=PROMPT_VERSION)
            return Coaching(latest, result, cached=True)

    # Generate outside the DB session: don't hold a connection open during an LLM call.
    # Only metrics go to the model, never the engineer's name or email.
    logger.info("No stored coaching guide for %s; generating", user_id)
    result = generate_efficiency_guide(without_pii(latest), severity,
                                       recent=[without_pii(d) for d in window[:-1]],
                                       savings=savings, prompt_version=PROMPT_VERSION)

    model = result.calls[-1].model if result.calls else provider.model   # the model that answered
    with db_session() as conn:
        record_request(conn, "guide", result.source, result.calls, user_id=user_id, model=model,
                       prompt_version=result.prompt_version)
        if not result.is_fallback:
            save_guide(conn, user_id, latest["date"], severity, result.prompt_version, model,
                       result.source, result.guide)
    return Coaching(latest, result, cached=False)
