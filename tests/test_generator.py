"""Tests for ai/guide_generator.py.

The Gemini client is replaced by the autouse `mock_gemini` fixture in conftest.py.
These tests previously patched `ai.guide_generator.model`, an attribute that stopped
existing when the module moved to the google-genai `client` API.
"""
from google.genai import errors

from ai.guide_generator import generate_efficiency_guide_v1 as generate_efficiency_guide
from ai.guide_generator import generate_team_report

TEAM_DATA = {"average_score": 60.5, "total_spend": 150.0, "critical_count": 2}
USER_DATA = {"efficiency_score": 45.0, "cache_ratio": 0.2, "opus_pct": 0.8}


def test_generate_team_report_success(mock_gemini):
    mock_gemini.models.generate_content.return_value.text = "This is a mocked AI summary for the team."

    result = generate_team_report(TEAM_DATA).text

    assert result == "This is a mocked AI summary for the team."
    mock_gemini.models.generate_content.assert_called_once()


def test_generate_team_report_strips_bold_markdown(mock_gemini):
    mock_gemini.models.generate_content.return_value.text = "Team is **doing well**."

    assert generate_team_report(TEAM_DATA).text == "Team is doing well."


def test_generate_team_report_fallback_on_error(mock_gemini):
    mock_gemini.models.generate_content.side_effect = Exception("API rate limit exceeded")

    report = generate_team_report(TEAM_DATA)
    assert "System Offline" in report.text and report.outcome == "unavailable" and report.calls == []


def test_generate_efficiency_guide_parses_numbered_list(mock_gemini):
    mock_gemini.models.generate_content.return_value.text = (
        "Here is your guide:\n1. Use compact more\n2. Cache **large** files"
    )

    result = generate_efficiency_guide(USER_DATA, "critical")

    assert result.source == "ai" and not result.is_fallback
    assert [t["desc"] for t in result.tasks] == ["Use compact more", "Cache large files"]
    assert all(t["title"] == "Optimization Action" for t in result.tasks)
    mock_gemini.models.generate_content.assert_called_once()


def test_generate_efficiency_guide_unnumbered_response_becomes_single_summary(mock_gemini):
    mock_gemini.models.generate_content.return_value.text = "- use compact\n- cache files"

    result = generate_efficiency_guide(USER_DATA)

    assert result.tasks == [{"title": "AI Summary", "desc": "- use compact\n- cache files"}]
    assert result.source == "ai"


def test_generate_efficiency_guide_rate_limit_returns_fallback_runbook(mock_gemini):
    mock_gemini.models.generate_content.side_effect = errors.ClientError(
        429, {"error": {"code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}})

    result = generate_efficiency_guide(USER_DATA)

    assert result.source == "rate_limited" and result.is_fallback
    assert result.tasks[0]["title"] == "System Notice: API Rate Limit"
    assert len(result.tasks) == 4


def test_generate_efficiency_guide_other_error_returns_offline_notice(mock_gemini):
    # BUG-02: fallbacks are now marked, so callers (e.g. the runbook cache) can tell them apart.
    mock_gemini.models.generate_content.side_effect = Exception("connection reset")

    result = generate_efficiency_guide(USER_DATA)

    assert result.source == "unavailable" and result.is_fallback
    assert result.tasks[0]["title"] == "AI Service Offline"


def test_non_rate_limit_api_error_is_unavailable_not_rate_limited(mock_gemini):
    mock_gemini.models.generate_content.side_effect = errors.ServerError(
        503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})

    assert generate_efficiency_guide(USER_DATA).source == "unavailable"
