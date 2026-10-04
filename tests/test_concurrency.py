"""CONC-01: a slow LLM call in one request must not stall unrelated requests.

Uses a real uvicorn server on loopback: TestClient runs each request on its own
event loop, which would hide event-loop blocking.
"""
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

import ai.coaching_service as coaching_service
from ai.guide_generator import GuideResult
from api.main import app
from tests.conftest import engineer_id

SIMULATED_LLM_SECONDS = 1.5


@pytest.fixture
def live_server(seeded_db):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _get(url):
    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=10) as response:
        response.read()
    return time.perf_counter() - start


def test_slow_runbook_generation_does_not_block_leaderboard(live_server, monkeypatch):
    def slow_generation(*args, **kwargs):
        time.sleep(SIMULATED_LLM_SECONDS)  # stands in for a blocking Gemini HTTP call
        return GuideResult(tasks=[{"title": "t", "desc": "d"}], source="ai")

    monkeypatch.setattr(coaching_service, "generate_efficiency_guide", slow_generation)
    _get(f"{live_server}/api/leaderboard")  # warm up

    runbook = threading.Thread(target=_get, args=(f"{live_server}/api/runbook-tasks/critical/{engineer_id(0)}",))
    runbook.start()
    time.sleep(0.2)  # let the runbook request reach the slow call
    latency = _get(f"{live_server}/api/leaderboard")
    runbook.join()

    print(f"leaderboard latency during slow generation: {latency:.3f}s")
    assert latency < 0.5, f"leaderboard waited {latency:.2f}s behind the LLM call"
