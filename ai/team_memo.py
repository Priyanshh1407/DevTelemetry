"""The manager's team memo (UPG-08): computed team facts in, structured memo out.

Same pipeline as the coaching guides: JSON schema, validation, one repair attempt, then a
rule-based memo. Validation also rejects any Claude Code command or file that doesn't exist
(ai/claude_code.py), so an invented feature never reaches a manager.
"""
import logging
from statistics import mean

from pydantic import ValidationError

from ai.claude_code import COST_COMMANDS, invented_files, unknown_commands
from ai.features import AREA_LABELS, coaching_facts
from ai.guide_generator import TeamReport
from ai.prompts import TEAM_PROMPT_VERSION, build_repair_prompt, build_team_memo_prompt
from ai.providers import AINotConfiguredError, AIRateLimitedError, get_provider
from ai.schemas import TEAM_MEMO_JSON_SCHEMA, TeamMemo
from core.scorer import POOL_DAYS
from core.severity import CRITICAL, severity_for_rank

logger = logging.getLogger(__name__)

AREAS = ("cache", "model_mix", "discipline")
FACTS_WINDOW_DAYS = POOL_DAYS   # the latest day plus the 6 before it (the /compact term's window)
ANOMALY_WINDOW_DAYS = 7


def team_facts(team, anomaly_count):
    """Facts for the memo. team: {user_id: [days, oldest first]} ending on the latest day;
    engineers without a row on the latest day are left out (as on the leaderboard)."""
    latest = max(days[-1]["date"] for days in team.values() if days)
    per_engineer = [coaching_facts(days[-1], days[-POOL_DAYS:-1]) for days in team.values()
                    if days and days[-1]["date"] == latest]
    scores = sorted((f["efficiency_score"] for f in per_engineer), reverse=True)
    n = len(per_engineer)
    lost = {a: round(mean(f["points_lost"][a] for f in per_engineer), 1) for a in AREAS}
    return {
        "team_size": n,
        "average_score": round(mean(scores), 1),
        "total_cost_usd": round(sum(days[-1].get("estimated_cost_usd") or 0 for days in team.values()
                                    if days and days[-1]["date"] == latest), 2),
        "points_lost": lost,
        "biggest_area": max(lost, key=lost.get),
        "weakest_area_counts": {a: sum(f["weakest_area"] == a for f in per_engineer) for a in AREAS},
        "critical_count": sum(severity_for_rank(rank, n) == CRITICAL for rank in range(1, n + 1)),
        "anomaly_count_7d": anomaly_count,
    }


_PRACTICES = {
    "cache": "Keep one session per task and a stable CLAUDE.md, so repeated context is read from cache "
             "instead of being sent again.",
    "model_mix": "Default to Sonnet, use Haiku for small edits and tests, and switch to Opus with /model "
                 "only for hard design work.",
    "discipline": "Run /compact between sub-tasks, and /clear before starting an unrelated task.",
}


def rule_based_memo(facts):
    """Deterministic memo from the facts, for when the model is unavailable or keeps failing."""
    ordered = sorted(AREAS, key=facts["points_lost"].get, reverse=True)
    biggest = ordered[0]
    summary = (f"The team of {facts['team_size']} averaged {facts['average_score']} / 100, with "
               f"${facts['total_cost_usd']:.2f} of estimated spend on the latest day. The biggest team-wide "
               f"gap is {AREA_LABELS[biggest]}, with {facts['points_lost'][biggest]} points lost per engineer "
               "on average.")
    if facts["anomaly_count_7d"]:
        summary += f" {facts['anomaly_count_7d']} days had unusual spend in the last 7 days."
    focus = [{"area": area,
              "why": f"{facts['weakest_area_counts'][area]} of {facts['team_size']} engineers lose the most "
                     f"points on {AREA_LABELS[area]}.",
              "practice": _PRACTICES[area]}
             for area in ordered[:2] if area == biggest or facts["weakest_area_counts"][area]]
    return {"summary": summary, "focus": focus}


def render_memo(memo):
    """Plain text for the digest email and the console."""
    lines = [memo["summary"], ""]
    lines += [f"Focus on {AREA_LABELS[f['area']]}: {f['why']} {f['practice']}" for f in memo["focus"]]
    return "\n".join(lines)


def _parse(text):
    """(memo, None) or (None, the problem, for the repair prompt)."""
    try:
        memo = TeamMemo.model_validate_json(text).model_dump()
    except ValidationError as e:
        return None, "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'reply'}: {err['msg']}"
                               for err in e.errors()[:3])
    rendered = render_memo(memo)
    invented = unknown_commands(rendered) + invented_files(rendered)
    if invented:
        return None, (f"it mentions {', '.join(invented)}, which Claude Code does not have; "
                      f"mention only {', '.join(COST_COMMANDS)}")
    return memo, None


def generate_team_memo(facts):
    """Never raises: on failure the rule-based memo comes back with the reason as outcome."""
    prompt = build_team_memo_prompt(facts, COST_COMMANDS)
    calls = []

    def result(memo, outcome):
        return TeamReport(text=render_memo(memo), outcome=outcome, calls=calls, memo=memo,
                          prompt_version=TEAM_PROMPT_VERSION)

    try:
        provider = get_provider()
        response = provider.generate(prompt, json_schema=TEAM_MEMO_JSON_SCHEMA)
        calls.append(response)
        memo, error = _parse(response.text)
        outcome = "ai"
        if memo is None:
            logger.warning("Team memo invalid (%s); asking for a repair", error)
            response = provider.generate(build_repair_prompt(prompt, error), json_schema=TEAM_MEMO_JSON_SCHEMA)
            calls.append(response)
            memo, error = _parse(response.text)
            outcome = "ai_repaired"
        if memo is None:
            logger.error("Team memo still invalid after repair (%s); using the rule-based memo", error)
            return result(rule_based_memo(facts), "invalid_output")
        return result(memo, outcome)
    except AIRateLimitedError:
        logger.warning("LLM rate limit hit; using the rule-based team memo")
        return result(rule_based_memo(facts), "rate_limited")
    except AINotConfiguredError:
        logger.warning("AI is not configured (no GEMINI_API_KEY); using the rule-based team memo")
        return result(rule_based_memo(facts), "unavailable")
    except Exception as e:
        logger.error("Team memo generation failed (%s): %s; using the rule-based memo", type(e).__name__, e)
        return result(rule_based_memo(facts), "unavailable")


def latest_team_memo():
    """The memo for the latest day, metered like every AI request; None without usage data."""
    from ai.store import record_request
    from core.anomaly import BASELINE_DAYS, recent_anomalies
    from core.db import db_session
    from core.queries import recent_days_by_engineer

    with db_session() as conn:
        team = recent_days_by_engineer(conn, FACTS_WINDOW_DAYS)
        if not team:
            return None
        anomalies = recent_anomalies(recent_days_by_engineer(conn, ANOMALY_WINDOW_DAYS + BASELINE_DAYS),
                                     ANOMALY_WINDOW_DAYS)
    report = generate_team_memo(team_facts(team, len(anomalies)))
    model = report.calls[-1].model if report.calls else get_provider().model
    with db_session() as conn:
        record_request(conn, "team_report", report.outcome, report.calls, model=model,
                       prompt_version=TEAM_PROMPT_VERSION)
    return report
