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

    monkeypatch.setattr(gg, "_client", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = gg.generate_efficiency_guide({"efficiency_score": 40.0})

    assert result[0]["title"] == "AI Service Offline"


def test_client_is_built_with_timeout_and_bounded_retries(monkeypatch):
    import ai.guide_generator as gg

    captured = {}
    monkeypatch.setattr(gg, "_client", None)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setattr(gg.genai, "Client", lambda **kwargs: captured.update(kwargs) or "client")

    assert gg.get_client() == "client"
    http_options = captured["http_options"]
    assert http_options.timeout == gg.LLM_TIMEOUT_MS
    assert http_options.retry_options.attempts == gg.LLM_MAX_ATTEMPTS
