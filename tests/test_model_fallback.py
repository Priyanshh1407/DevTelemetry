"""When the main Gemini model is rate-limited or overloaded, the app retries once on a lighter
model with its own quota (gemini-3.5-flash-lite) before falling back to the rule-based guide."""
from unittest.mock import MagicMock

import pytest
from google.genai import errors

from ai.providers import AIRateLimitedError, AIUnavailableError, GeminiProvider, get_provider, price_per_million
from tests.conftest import MOCK_GUIDE_JSON, engineer_id

LITE = "gemini-3.5-flash-lite"


def rate_limited():
    return errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})


def overloaded():
    return errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})


def ok_response():
    response = MagicMock()
    response.text = MOCK_GUIDE_JSON
    response.usage_metadata.prompt_token_count = 1000
    response.usage_metadata.candidates_token_count = 300
    response.usage_metadata.thoughts_token_count = 200
    return response


def models_called(mock_gemini):
    return [c.kwargs["model"] for c in mock_gemini.models.generate_content.call_args_list]


def test_default_fallback_is_the_latest_flash_lite():
    provider = get_provider()
    assert (provider.model, provider.fallback_model) == ("gemini-3.8-flash", LITE)


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
def test_rate_limit_or_overload_retries_once_on_the_fallback_model(mock_gemini, failure):
    mock_gemini.models.generate_content.side_effect = [failure(), ok_response()]

    response = GeminiProvider("gemini-3.8-flash", fallback_model=LITE).generate("hi")

    assert models_called(mock_gemini) == ["gemini-3.8-flash", LITE]
    assert response.model == LITE                          # metered and stored as what really answered
    price_in, price_out = price_per_million(LITE)
    assert response.cost_usd == round((1000 * price_in + 500 * price_out) / 1e6, 6)


def test_other_errors_do_not_switch_models(mock_gemini):
    bad_request = errors.ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}})
    mock_gemini.models.generate_content.side_effect = bad_request

    with pytest.raises(AIUnavailableError):
        GeminiProvider("gemini-3.8-flash", fallback_model=LITE).generate("hi")
    assert models_called(mock_gemini) == ["gemini-3.8-flash"]


def test_when_both_models_are_rate_limited_the_error_is_a_rate_limit(mock_gemini):
    mock_gemini.models.generate_content.side_effect = [rate_limited(), rate_limited()]

    with pytest.raises(AIRateLimitedError):
        GeminiProvider("gemini-3.8-flash", fallback_model=LITE).generate("hi")


def test_the_fallback_can_be_switched_off(mock_gemini, monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "")
    mock_gemini.models.generate_content.side_effect = rate_limited()

    with pytest.raises(AIRateLimitedError):
        get_provider().generate("hi")
    assert models_called(mock_gemini) == ["gemini-3.8-flash"]


def test_a_guide_from_the_fallback_model_is_stored_under_its_own_name(client, seeded_db, mock_gemini, query):
    mock_gemini.models.generate_content.side_effect = [rate_limited(), ok_response()]
    first = client.get(f"/api/runbook-tasks/critical/{engineer_id(0)}").json()

    mock_gemini.models.generate_content.side_effect = None
    second = client.get(f"/api/runbook-tasks/critical/{engineer_id(0)}").json()

    assert first["source"] == "ai" and second["cached"] is True     # reused, no new call
    assert mock_gemini.models.generate_content.call_count == 2
    assert query("SELECT model FROM coaching_guides") == [{"model": LITE}]
    assert {r["model"] for r in query("SELECT model FROM ai_requests")} == {LITE}


def test_latency_includes_the_failed_attempt_on_the_main_model(mock_gemini, monkeypatch):
    import ai.providers as providers

    clock = iter([0.0, 3.5])   # timed from before the main attempt (fails after ~2 s) to the fallback answer
    monkeypatch.setattr(providers.time, "perf_counter", lambda: next(clock))
    mock_gemini.models.generate_content.side_effect = [rate_limited(), ok_response()]

    response = GeminiProvider("gemini-3.8-flash", fallback_model=LITE).generate("hi")

    assert response.latency_ms == 3500    # what the user waited, not just the second call


def test_after_a_failure_the_main_model_is_skipped_for_a_cooldown(mock_gemini, monkeypatch):
    import ai.providers as providers

    now = [1000.0]
    monkeypatch.setattr(providers.time, "monotonic", lambda: now[0])
    mock_gemini.models.generate_content.side_effect = [rate_limited(), ok_response(), ok_response(), ok_response()]
    provider = GeminiProvider("gemini-3.8-flash", fallback_model=LITE)

    provider.generate("first")                       # main fails -> fallback
    provider.generate("second")                      # within the cooldown: straight to the fallback
    now[0] += providers.MAIN_MODEL_COOLDOWN_S + 1
    provider.generate("third")                       # cooldown over: the main model is tried again

    assert models_called(mock_gemini) == ["gemini-3.8-flash", LITE, LITE, "gemini-3.8-flash"]
