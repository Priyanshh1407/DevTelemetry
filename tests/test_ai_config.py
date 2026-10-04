"""ERR-01: the API must boot and serve non-AI endpoints without a Gemini key."""
import os
import subprocess
import sys

from tests.conftest import PROJECT_ROOT

SCRIPT = """
from fastapi.testclient import TestClient
from core.db import init_db
init_db()
from api.main import app
print(TestClient(app).get('/api/leaderboard').status_code)
"""


def test_api_boots_without_gemini_key(tmp_path):
    # Runs in a fresh interpreter: the key is read when the app is imported, and this
    # test process already imported it. Empty values win over .env (load_dotenv never overrides).
    env = {**os.environ, "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "DB_PATH": str(tmp_path / "t.db")}

    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=PROJECT_ROOT, env=env,
                            capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "200"


def test_missing_key_degrades_to_fallback_instead_of_raising(monkeypatch):
    import ai.guide_generator as gg
    import ai.providers as providers

    monkeypatch.setattr(providers, "_client", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = gg.generate_efficiency_guide({"session_count": 2, "compact_uses": 0})

    assert result.source == "unavailable" and result.is_fallback
    assert result.guide["actions"]  # a rule-based guide, not an error message


def test_client_is_built_with_timeout_and_bounded_retries(monkeypatch):
    import ai.providers as providers

    captured = {}
    monkeypatch.setattr(providers, "_client", None)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(providers.genai, "Client", lambda **kwargs: captured.update(kwargs) or "client")

    assert providers.get_client() == "client"
    http_options = captured["http_options"]
    assert http_options.timeout == providers.LLM_TIMEOUT_MS
    assert http_options.retry_options.attempts == providers.LLM_MAX_ATTEMPTS


def test_provider_reports_tokens_latency_and_cost(mock_gemini):
    from ai.providers import GeminiProvider

    from ai.providers import price_per_million

    response = GeminiProvider().generate("hello")

    assert (response.input_tokens, response.output_tokens) == (1000, 500)   # thinking counts as output
    price_in, price_out = price_per_million("gemini-3.8-flash")
    assert response.cost_usd == round((1000 * price_in + 500 * price_out) / 1_000_000, 6)
    assert response.latency_ms >= 0 and response.model == "gemini-3.8-flash"


def test_gemini_prices_follow_the_announced_schedule():
    from datetime import date

    from ai.providers import price_per_million

    assert price_per_million("gemini-3.8-flash", date(2026, 12, 31)) == (0.75, 3.75)
    assert price_per_million("gemini-3.8-flash", date(2027, 1, 1)) == (1.50, 7.50)   # doubles in 2027
    assert price_per_million("gemini-2.5-flash", date(2026, 10, 4)) == (0.30, 2.50)
    assert price_per_million("some-future-model") is None


def test_model_can_be_chosen_with_an_env_var(monkeypatch):
    from ai.providers import get_provider

    assert get_provider().model == "gemini-3.8-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    assert get_provider().model == "gemini-3.5-flash"


def test_json_mode_sends_the_schema_to_the_model(mock_gemini):
    from ai.providers import GeminiProvider

    schema = {"type": "object", "properties": {"headline": {"type": "string"}}}
    GeminiProvider().generate("hello", json_schema=schema)

    config = mock_gemini.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema
