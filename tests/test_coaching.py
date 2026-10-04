"""UPG-01: structured, grounded coaching guides (prompt v2).

The model must return JSON matching ai.schemas.CoachingGuide. Invalid output gets one
repair attempt; after that, or when the provider is down or rate-limited, a rule-based
guide built from the engineer's real numbers is returned instead.
"""
import json

import pytest
from google.genai import errors

from ai.features import coaching_facts
from ai.guide_generator import generate_efficiency_guide
from ai.prompts import PROMPT_VERSION

DAY = {"date": "2026-03-31", "input_tokens": 600_000, "cache_read_tokens": 300_000, "cache_write_tokens": 100_000,
       "output_tokens": 20_000, "opus_pct": 0.5, "sonnet_pct": 0.4, "haiku_pct": 0.1,
       "session_count": 4, "compact_uses": 1, "estimated_cost_usd": 9.87, "git_commits": 3}
RECENT = [dict(DAY, date=f"2026-03-{d:02d}", compact_uses=2) for d in range(25, 31)]


def valid_guide(first_focus="cache", n=2):
    actions = [{"title": f"Action {i}", "problem": "Only 30.0% of your prompt tokens came from cache.",
                "fix": "Keep one long-lived session per task so the cached context is reused.",
                "focus": first_focus if i == 0 else "discipline"} for i in range(n)]
    return json.dumps({"headline": "Your cache is the biggest opportunity.", "actions": actions})


def responses(mock_gemini, *texts):
    mock_gemini.models.generate_content.side_effect = None
    results = []
    for text in texts:
        if isinstance(text, Exception):
            results.append(text)
            continue
        r = type(mock_gemini.models.generate_content.return_value)()
        r.text = text
        r.usage_metadata.prompt_token_count = 1000
        r.usage_metadata.candidates_token_count = 300
        r.usage_metadata.thoughts_token_count = 0
        results.append(r)
    mock_gemini.models.generate_content.side_effect = results


def prompts_sent(mock_gemini):
    return [c.kwargs["contents"] for c in mock_gemini.models.generate_content.call_args_list]


# ── facts: the ground truth the model may cite ─────────────────────────────

def test_facts_are_computed_from_the_data():
    facts = coaching_facts(DAY, RECENT)

    assert facts["cache_hit_pct"] == 30.0               # 300k of 1M prompt tokens
    assert (facts["opus_pct"], facts["sonnet_pct"], facts["haiku_pct"]) == (50.0, 40.0, 10.0)
    assert (facts["compacts_7d"], facts["sessions_7d"]) == (13, 28)   # 6 x 2 + 1 over 7 x 4 sessions
    assert facts["compact_rate_7d_pct"] == 46.4
    assert facts["weakest_area"] == "cache"              # 40 - 12 = 28 points lost, the most
    assert "name" not in facts and "email" not in facts


# ── the happy path and the repair loop ──────────────────────────────────────

def test_valid_json_becomes_a_structured_guide(mock_gemini):
    responses(mock_gemini, valid_guide())

    result = generate_efficiency_guide(DAY, "moderate", recent=RECENT)

    assert result.source == "ai" and not result.is_fallback
    assert result.guide["headline"] == "Your cache is the biggest opportunity."
    assert [t["title"] for t in result.tasks] == ["Action 0", "Action 1"]
    assert "came from cache" in result.tasks[0]["desc"] and "long-lived session" in result.tasks[0]["desc"]
    assert result.prompt_version == PROMPT_VERSION
    assert len(result.calls) == 1 and result.calls[0].input_tokens == 1000


@pytest.mark.parametrize("bad", [
    "1. Not JSON at all",
    json.dumps({"headline": "x", "actions": []}),                                         # no actions
    json.dumps({"headline": "Fine headline", "actions": [{"title": "T", "problem": "p", "fix": "f",
                                                          "focus": "vibes"}]}),           # off-schema
])
def test_invalid_output_gets_one_repair_attempt(mock_gemini, bad):
    responses(mock_gemini, bad, valid_guide())

    result = generate_efficiency_guide(DAY, "moderate", recent=RECENT)

    assert result.source == "ai_repaired" and not result.is_fallback
    first, second = prompts_sent(mock_gemini)
    assert "previous reply was not valid" in second and first in second
    assert len(result.calls) == 2


def test_still_invalid_after_repair_falls_back_to_rules(mock_gemini):
    responses(mock_gemini, "nope", "still nope")

    result = generate_efficiency_guide(DAY, "moderate", recent=RECENT)

    assert result.source == "invalid_output" and result.is_fallback
    assert len(result.calls) == 2   # bounded: never more than one repair


# ── personalized fallback (was a generic "AI Service Offline" list) ────────

@pytest.mark.parametrize("failure, source", [
    (errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
     "rate_limited"),
    (errors.ServerError(503, {"error": {"code": 503, "message": "down", "status": "UNAVAILABLE"}}), "unavailable"),
])
def test_provider_failures_get_a_rule_based_guide_with_real_numbers(mock_gemini, failure, source):
    responses(mock_gemini, failure)

    result = generate_efficiency_guide(DAY, "critical", recent=RECENT)

    assert result.source == source and result.is_fallback
    assert result.guide["actions"][0]["focus"] == "cache"          # weakest area first
    text = " ".join(t["desc"] for t in result.tasks)
    assert "30.0%" in text and "50.0%" in text and "46.4%" in text  # the engineer's own numbers


def test_missing_key_gets_the_rule_based_guide(mock_gemini, monkeypatch):
    import ai.providers as providers

    monkeypatch.setattr(providers, "_client", None)

    result = generate_efficiency_guide(DAY, "moderate", recent=RECENT)

    assert result.source == "unavailable"
    assert "30.0%" in result.tasks[0]["desc"]


# ── prompt v2 ──────────────────────────────────────────────────────────────

def test_prompt_lists_the_facts_and_the_grounding_rules(mock_gemini):
    responses(mock_gemini, valid_guide())

    generate_efficiency_guide(DAY, "moderate", recent=RECENT)

    prompt = prompts_sent(mock_gemini)[0]
    for fact in ("30.0%", "Opus 50.0%", "46.4%", "13 of 28", "$9.87", "Weakest area: cache"):
        assert fact in prompt
    assert "must appear in FACTS" in prompt
    assert mock_gemini.models.generate_content.call_args.kwargs["config"].response_mime_type == "application/json"


def test_top_performers_are_not_told_they_are_below_average(mock_gemini):
    responses(mock_gemini, valid_guide())

    generate_efficiency_guide(DAY, "low", recent=RECENT)

    prompt = prompts_sent(mock_gemini)[0]
    assert "below average" not in prompt
    assert "top performers" in prompt
