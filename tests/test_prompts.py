"""Golden-file tests: the exact prompts sent to the LLM.

Prompt text is behavior: any change should be a deliberate, reviewed diff to these files
(and, from UPG-01 on, a PROMPT_VERSION bump), never a side effect of refactoring.
Regenerate after an intended change with:  UPDATE_GOLDEN=1 pytest tests/test_prompts.py
"""
import os
import pathlib

import pytest

from ai.guide_generator import generate_efficiency_guide, generate_team_report

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
    generate_efficiency_guide(ENGINEER, severity)
    check(f"guide_prompt_{severity}.txt", sent_prompt(mock_gemini))


def test_team_report_prompt(mock_gemini):
    generate_team_report(TEAM)
    check("team_report_prompt.txt", sent_prompt(mock_gemini))
