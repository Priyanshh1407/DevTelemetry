"""UPG-01 persistence + UPG-04 metering.

Successful guides are stored in coaching_guides (they survive restarts and are shared across
workers). Every guide request is recorded in ai_requests with its outcome, tokens, latency
and cost, and /api/ai-stats summarizes them.
"""
import pytest

from ai.prompts import PROMPT_VERSION
from ai.providers import DEFAULT_GEMINI_MODEL, price_per_million
from tests.conftest import engineer_id

# One mocked model call: 1,000 input + 500 output tokens (conftest), at the default model's price.
_IN, _OUT = price_per_million(DEFAULT_GEMINI_MODEL)
CALL_COST = (1000 * _IN + 500 * _OUT) / 1e6


def rows(query, sql):
    return query(sql)


def runbook(client, i=0, severity="critical"):
    return client.get(f"/api/runbook-tasks/{severity}/{engineer_id(i)}").json()


def test_guides_survive_a_restart_because_they_live_in_the_database(client, seeded_db, mock_gemini, query):
    runbook(client)

    # There is no in-process cache left to clear: a "restart" changes nothing.
    second = runbook(client)

    assert mock_gemini.models.generate_content.call_count == 1
    assert second["cached"] is True
    stored = rows(query, "SELECT user_id, metrics_date, severity, prompt_version, model, source FROM coaching_guides")
    assert stored == [{"user_id": engineer_id(0), "metrics_date": "2026-01-03", "severity": "critical",
                       "prompt_version": PROMPT_VERSION, "model": "gemini-3.8-flash", "source": "ai"}]


def test_a_new_prompt_version_does_not_reuse_old_guides(client, seeded_db, mock_gemini, monkeypatch):
    import ai.coaching_service as service

    runbook(client)
    monkeypatch.setattr(service, "PROMPT_VERSION", "v4")
    runbook(client)

    assert mock_gemini.models.generate_content.call_count == 2


def test_fallback_guides_are_served_but_never_stored(client, seeded_db, mock_gemini, query):
    mock_gemini.models.generate_content.side_effect = Exception("down")

    assert runbook(client)["source"] == "unavailable"
    assert rows(query, "SELECT COUNT(*) AS n FROM coaching_guides")[0]["n"] == 0


def test_every_request_is_metered(client, seeded_db, mock_gemini, query):
    runbook(client)
    runbook(client)                     # cache hit
    mock_gemini.models.generate_content.side_effect = Exception("down")
    runbook(client, i=1)                # fallback

    logged = rows(query, "SELECT purpose, outcome, user_id, llm_calls, input_tokens, output_tokens, cost_usd "
                         "FROM ai_requests ORDER BY id")
    assert [(r["outcome"], r["llm_calls"]) for r in logged] == [("ai", 1), ("cache_hit", 0), ("unavailable", 0)]
    assert logged[0]["input_tokens"] == 1000 and logged[0]["output_tokens"] == 500
    assert logged[0]["cost_usd"] == pytest.approx(CALL_COST)
    assert {r["purpose"] for r in logged} == {"guide"}


def test_ai_stats_summarize_the_requests(client, seeded_db, mock_gemini):
    runbook(client, i=0)
    runbook(client, i=0)                # cache hit
    runbook(client, i=1)
    mock_gemini.models.generate_content.side_effect = Exception("down")
    runbook(client, i=2)                # fallback

    stats = client.get("/api/ai-stats").json()

    assert stats["requests"] == 4
    assert stats["by_outcome"] == {"ai": 2, "cache_hit": 1, "unavailable": 1}
    assert stats["cache_hit_rate"] == 0.25
    assert stats["fallback_rate"] == pytest.approx(1 / 3)          # of the 3 non-cached requests
    assert stats["llm_calls"] == 2
    assert stats["cost_usd"] == pytest.approx(2 * CALL_COST)
    assert stats["cost_per_generated_guide_usd"] == pytest.approx(CALL_COST)
    assert set(stats["latency_ms"]) == {"p50", "p95"}


def test_ai_stats_with_no_requests(client):
    stats = client.get("/api/ai-stats").json()
    assert stats["requests"] == 0 and stats["cache_hit_rate"] is None and stats["latency_ms"] == {"p50": None, "p95": None}


def test_the_cli_and_the_alert_worker_are_metered_too(seeded_db, mock_gemini, query):
    import main
    from data.alert_worker import run_weekly_telemetry_check

    main.main()
    run_weekly_telemetry_check()

    purposes = [r["purpose"] for r in rows(query, "SELECT purpose FROM ai_requests")]
    assert purposes.count("guide") == 5          # the CLI coaches the bottom 5
    assert purposes.count("team_report") == 2    # CLI memo + alert worker digest memo


def test_unused_ai_guides_table_is_dropped_but_only_when_empty(tmp_path, monkeypatch):
    import sqlite3

    from core.db import init_db

    empty, used = tmp_path / "empty.db", tmp_path / "used.db"
    for path, rows_sql in ((empty, ""), (used, "INSERT INTO ai_guides VALUES (1, 'u', '2026-01-01', 'g', 'low');")):
        conn = sqlite3.connect(path)
        conn.executescript("CREATE TABLE ai_guides (id INTEGER PRIMARY KEY, user_id TEXT, date TEXT, "
                           "guide_text TEXT, severity TEXT);" + rows_sql)
        conn.close()

    for path, should_exist in ((empty, False), (used, True)):
        monkeypatch.setenv("DB_PATH", str(path))
        init_db()
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        assert ("ai_guides" in tables) is should_exist
        assert {"coaching_guides", "ai_requests"} <= tables
