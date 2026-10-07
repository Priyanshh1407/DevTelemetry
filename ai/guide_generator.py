import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv
from pydantic import ValidationError

from ai.fallback import rule_based_guide
from ai.features import coaching_facts
from ai.prompts import (PROMPT_VERSION, PROMPT_VERSION_V3, build_guide_prompt, build_guide_prompt_v2,
                        build_guide_prompt_v3, build_repair_prompt, build_team_report_prompt)
from ai.providers import AINotConfiguredError, AIRateLimitedError, AIUnavailableError, get_provider
from ai.schemas import GUIDE_JSON_SCHEMA, CoachingGuide

load_dotenv()

logger = logging.getLogger(__name__)

# Re-exported for callers that catch it from here.
__all__ = ["AIUnavailableError", "GuideResult", "TeamReport", "generate_efficiency_guide",
           "generate_efficiency_guide_v1", "generate_team_report", "tasks_from_guide"]

AI_SOURCES = ("ai", "ai_repaired")


@dataclass
class GuideResult:
    """A guide plus where it came from, so callers can tell model answers from fallbacks.

    source: "ai" (valid on the first try), "ai_repaired" (valid after one repair retry), or a
    fallback reason: "invalid_output", "rate_limited", "unavailable".
    guide: the structured guide {headline, actions: [{title, problem, fix, focus}]} (v2).
    calls: one LLMResponse per model call (tokens, latency, cost) for metering.
    """
    tasks: list
    source: str
    guide: dict | None = None
    calls: list = field(default_factory=list)
    prompt_version: str | None = None

    @property
    def is_fallback(self):
        return self.source not in AI_SOURCES


def tasks_from_guide(guide):
    """The dashboard's runbook shows title + description per task."""
    return [{"title": a["title"], "desc": f"{a['problem']} {a['fix']}"} for a in guide["actions"]]


def _parse_guide(text):
    """Returns (guide dict, None) or (None, short error message for the repair prompt)."""
    try:
        return CoachingGuide.model_validate_json(text).model_dump(), None
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'reply'}: {err['msg']}"
                             for err in e.errors()[:3])
        return None, problems


def generate_efficiency_guide(day, severity="moderate", recent=(), savings=None, prompt_version=PROMPT_VERSION):
    """Structured coaching guide (prompt v2, or v3 with computed savings) for one engineer-day.
    Never raises.

    `day` and `recent` (earlier days, oldest first) must already be free of identity
    (see core.queries.without_pii): only metrics are sent to the model. `savings` is
    core.whatif.savings_facts output, used by prompt v3 and the rule-based fallback.
    """
    facts = coaching_facts(day, recent, savings=savings)
    build = build_guide_prompt_v3 if prompt_version == PROMPT_VERSION_V3 else build_guide_prompt_v2
    prompt = build(facts, severity)
    provider = get_provider()
    calls = []

    def fallback(source):
        guide = rule_based_guide(facts)
        return GuideResult(tasks=tasks_from_guide(guide), source=source, guide=guide, calls=calls,
                           prompt_version=prompt_version)

    try:
        response = provider.generate(prompt, json_schema=GUIDE_JSON_SCHEMA)
        calls.append(response)
        guide, error = _parse_guide(response.text)
        source = "ai"
        if guide is None:
            # One repair attempt with the validation error, then give up (bounded cost).
            logger.warning("Guide output invalid (%s); asking for a repair", error)
            response = provider.generate(build_repair_prompt(prompt, error), json_schema=GUIDE_JSON_SCHEMA)
            calls.append(response)
            guide, error = _parse_guide(response.text)
            source = "ai_repaired"
        if guide is None:
            logger.error("Guide output still invalid after repair (%s); using the rule-based guide", error)
            return fallback("invalid_output")
        return GuideResult(tasks=tasks_from_guide(guide), source=source, guide=guide, calls=calls,
                           prompt_version=prompt_version)
    except AIRateLimitedError:
        logger.warning("LLM rate limit hit; using the rule-based guide")
        return fallback("rate_limited")
    except AINotConfiguredError:
        logger.warning("AI is not configured (no GEMINI_API_KEY); using the rule-based guide")
        return fallback("unavailable")
    except Exception as e:
        logger.error("Guide generation failed (%s): %s; using the rule-based guide", type(e).__name__, e)
        return fallback("unavailable")


def generate_efficiency_guide_v1(engineer_data, severity="moderate"):
    """Prompt v1 pipeline (raw row in, numbered plain text out), kept as the eval baseline.
    Never raises: on failure it returns a static fallback with source != "ai".
    """
    prompt = build_guide_prompt(engineer_data, severity)

    try:
        response = get_provider().generate(prompt)
        response_text = response.text

        tasks = []
        for line in response_text.split('\n'):
            line = line.strip()
            if line and line[0].isdigit() and '. ' in line[:4]:
                clean_text = line.split('. ', 1)[1].strip()

                # Strip out stray markdown asterisks that the AI ignores rules to include
                clean_text = clean_text.replace('**', '').replace('*', '')

                tasks.append({
                    "title": "Optimization Action",
                    "desc": clean_text
                })

        if not tasks:
            tasks = [{"title": "AI Summary", "desc": response_text.replace('**', '')}]

        return GuideResult(tasks=tasks, source="ai", calls=[response], prompt_version="v1")

    except AIRateLimitedError:
        logger.warning("Gemini rate limit hit; serving the fallback runbook")
        return GuideResult(source="rate_limited", tasks=[
            {"title": "System Notice: API Rate Limit", "desc": "Personalized generation is paused due to Gemini API limits. Showing standard procedures."},
            {"title": "Audit Token Looping", "desc": "Check agent logs for repetitive, failing task loops."},
            {"title": "Enforce Model Tiering", "desc": "Shift non-essential background tasks to Haiku/Flash models."},
            {"title": "Consolidate Prompts", "desc": "Batch multiple instructions into a single context window."}
        ])
    except Exception as e:
        # Total API failure (no internet, no API key, server error)
        logger.error("Gemini guide generation failed (%s): %s", type(e).__name__, e)
        return GuideResult(source="unavailable", tasks=[
            {"title": "AI Service Offline", "desc": "Unable to connect to the intelligence engine."},
            {"title": "Manual Intervention", "desc": "Please review the raw telemetry metrics directly."}
        ])


@dataclass
class TeamReport:
    text: str
    outcome: str          # ai | rate_limited | unavailable
    calls: list = field(default_factory=list)


def generate_team_report(team_summary):
    """The manager digest's two-paragraph memo. Never raises."""
    prompt = build_team_report_prompt(team_summary)

    try:
        response = get_provider().generate(prompt)
        return TeamReport(text=response.text.replace('**', ''), outcome="ai", calls=[response])
    except AIRateLimitedError:
        logger.warning("LLM rate limit hit for the team report")
        return TeamReport(text="The AI team memo is unavailable right now (AI provider rate limit). "
                               "The leaderboard has today's numbers.", outcome="rate_limited")
    except AINotConfiguredError:
        logger.warning("AI is not configured (no GEMINI_API_KEY); skipping the team memo")
        return TeamReport(text="No AI team memo: GEMINI_API_KEY is not configured. "
                               "The leaderboard has today's numbers.", outcome="unavailable")
    except Exception as e:
        logger.error("Gemini team report failed (%s): %s", type(e).__name__, e)
        return TeamReport(text="The AI team memo is unavailable right now (the AI provider could not be reached). "
                               "The leaderboard has today's numbers.", outcome="unavailable")
