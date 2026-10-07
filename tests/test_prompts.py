"""Golden-file tests: the exact prompts sent to the LLM.

Prompt text is behavior: any change should be a deliberate, reviewed diff to these files
(and, from UPG-01 on, a PROMPT_VERSION bump), never a side effect of refactoring.
Regenerate after an intended change with:  UPDATE_GOLDEN=1 pytest tests/test_prompts.py
"""
import os
import pathlib

import pytest

from ai.guide_generator import generate_efficiency_guide, generate_efficiency_guide_v1, generate_team_report

GOLDEN = pathlib.Path(__file__).parent / "golden"
ENGINEER = {"name": "Engineer 00", "date": "2026-01-03", "efficiency_score": 41.5, "input_tokens": 120000,
            "cache_read_tokens": 60000, "opus_pct": 0.4}
TEAM = {"average_score": 61.2, "total_spend": 131.4, "critical_count": 2}


def sent_prompt(mock_gemini):
    return mock_gemini.models.generate_content.call_args.kwargs["contents"]


def check(name, text):
    path = GOLDEN / name
    if os.getenv("UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8", newline="\n")
    assert text == path.read_text(encoding="utf-8"), f"prompt changed: review and regenerate {path.name}"


@pytest.mark.parametrize("severity", ["critical", "moderate", "low"])
def test_guide_prompt(mock_gemini, severity):
    generate_efficiency_guide_v1(ENGINEER, severity)
    check(f"guide_prompt_{severity}.txt", sent_prompt(mock_gemini))


V2_DAY = {"date": "2026-03-31", "input_tokens": 600_000, "cache_read_tokens": 300_000, "cache_write_tokens": 100_000,
          "output_tokens": 20_000, "opus_pct": 0.5, "sonnet_pct": 0.4, "haiku_pct": 0.1,
          "session_count": 4, "compact_uses": 1, "estimated_cost_usd": 9.87}


@pytest.mark.parametrize("severity", ["critical", "moderate", "low"])
def test_guide_prompt_v2(mock_gemini, severity):
    generate_efficiency_guide(V2_DAY, severity, recent=[dict(V2_DAY, compact_uses=2)] * 6)
    check(f"guide_prompt_v2_{severity}.txt", sent_prompt(mock_gemini))


def test_team_report_prompt(mock_gemini):
    generate_team_report(TEAM)
    check("team_report_prompt.txt", sent_prompt(mock_gemini))


SAVINGS = {"window_days": 30, "cache_target_pct": 82.4, "saving_month_usd_cache": 61.27,
           "opus_target_pct": 14.0, "saving_month_usd_model": 0.0}


@pytest.mark.parametrize("severity", ["critical", "moderate", "low"])
def test_guide_prompt_v3(mock_gemini, severity):
    generate_efficiency_guide(V2_DAY, severity, recent=[dict(V2_DAY, compact_uses=2)] * 6, savings=SAVINGS,
                              prompt_version="v3")
    check(f"guide_prompt_v3_{severity}.txt", sent_prompt(mock_gemini))


def test_team_memo_prompt():
    from ai.claude_code import COST_COMMANDS
    from ai.prompts import build_team_memo_prompt

    facts = {"team_size": 10, "average_score": 61.2, "total_cost_usd": 131.4,
             "points_lost": {"cache": 14.3, "model_mix": 12.1, "discipline": 9.8}, "biggest_area": "cache",
             "weakest_area_counts": {"cache": 5, "model_mix": 3, "discipline": 2}, "critical_count": 2,
             "anomaly_count_7d": 1}
    check("team_memo_prompt_v2.txt", build_team_memo_prompt(facts, COST_COMMANDS))
