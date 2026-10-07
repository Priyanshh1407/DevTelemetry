"""UPG-08: the manager's team memo is grounded in computed team facts and can't recommend
Claude Code features that don't exist."""
import json
from datetime import date, timedelta

import pytest

import ai.team_memo as team_memo
from ai.claude_code import COST_COMMANDS, KNOWN_COMMANDS, invented_files, unknown_commands
from google.genai import errors

from ai.team_memo import TEAM_PROMPT_VERSION, generate_team_memo, render_memo, rule_based_memo, team_facts

START = date(2026, 3, 25)


def eng_days(hit=0.7, opus=0.2, compacts=2, cost=10.0, n=7):
    days = []
    for i in range(n):
        read = int(1_000_000 * hit)
        days.append({"date": (START + timedelta(days=i)).isoformat(), "input_tokens": 1_000_000 - read,
                     "cache_read_tokens": read, "cache_write_tokens": 0, "output_tokens": 10_000,
                     "opus_pct": opus, "sonnet_pct": round(0.9 - opus, 2), "haiku_pct": 0.1,
                     "session_count": 4, "compact_uses": compacts, "estimated_cost_usd": cost})
    return days


def team():
    # Eight engineers whose weakest area is caching, two whose weakest is /compact.
    t = {f"c{i}": eng_days(hit=0.3 + 0.02 * i, compacts=3) for i in range(8)}
    t.update({f"d{i}": eng_days(hit=0.9, compacts=0, cost=20.0) for i in range(2)})
    return t


def test_team_facts_are_computed_from_the_data():
    facts = team_facts(team(), anomaly_count=3)

    assert facts["team_size"] == 10
    assert facts["total_cost_usd"] == pytest.approx(8 * 10 + 2 * 20)
    assert facts["biggest_area"] == "cache"
    assert facts["weakest_area_counts"] == {"cache": 8, "model_mix": 0, "discipline": 2}
    assert facts["critical_count"] == 2
    assert facts["anomaly_count_7d"] == 3
    assert set(facts["points_lost"]) == {"cache", "model_mix", "discipline"}
    assert 0 < facts["average_score"] < 100


def test_a_small_team_has_no_critical_tier():
    small = dict(list(team().items())[:5])
    assert team_facts(small, anomaly_count=0)["critical_count"] == 0


def memo_json(area="cache", text="Keep sessions focused and run /compact between sub-tasks."):
    return json.dumps({"summary": "The team averaged a solid score this week with steady spend.",
                       "focus": [{"area": area, "why": "Caching loses the most points team-wide.",
                                  "practice": text}]})


def reply(mock_gemini, *texts):
    responses = []
    for text in texts:
        r = type(mock_gemini.models.generate_content.return_value)()
        r.text = text
        r.usage_metadata.prompt_token_count = 500
        r.usage_metadata.candidates_token_count = 100
        r.usage_metadata.thoughts_token_count = 0
        responses.append(r)
    mock_gemini.models.generate_content.side_effect = responses


def test_a_valid_memo_is_used(mock_gemini):
    reply(mock_gemini, memo_json())

    report = generate_team_memo(team_facts(team(), 0))

    assert report.outcome == "ai" and report.memo["focus"][0]["area"] == "cache"
    assert "steady spend" in report.text and "/compact" in report.text
    assert report.prompt_version == TEAM_PROMPT_VERSION and len(report.calls) == 1


def test_an_invented_command_is_repaired(mock_gemini):
    reply(mock_gemini, memo_json(text="Add a .claudedir file and run /optimize-tokens daily."), memo_json())

    report = generate_team_memo(team_facts(team(), 0))

    assert report.outcome == "ai_repaired" and len(report.calls) == 2
    repair_prompt = mock_gemini.models.generate_content.call_args_list[1].kwargs["contents"]
    assert "/optimize-tokens" in repair_prompt and ".claudedir" in repair_prompt


def test_still_invented_after_repair_falls_back_to_the_rule_based_memo(mock_gemini):
    bad = memo_json(text="Run /optimize-tokens every morning.")
    reply(mock_gemini, bad, bad)

    report = generate_team_memo(team_facts(team(), 0))

    assert report.outcome == "invalid_output"
    assert report.memo == rule_based_memo(team_facts(team(), 0))
    assert "/optimize-tokens" not in report.text


@pytest.mark.parametrize("error, outcome", [
    (errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
     "rate_limited"),
    (errors.ServerError(503, {"error": {"code": 503, "message": "down", "status": "UNAVAILABLE"}}), "unavailable"),
])
def test_provider_failures_get_the_rule_based_memo(mock_gemini, error, outcome):
    mock_gemini.models.generate_content.side_effect = [error, error]   # main and fallback model
    report = generate_team_memo(team_facts(team(), 0))
    assert report.outcome == outcome and report.memo == rule_based_memo(team_facts(team(), 0))


def test_missing_key_gets_the_rule_based_memo(mock_gemini, monkeypatch):
    from ai import providers
    monkeypatch.setattr(providers, "_client", None)
    report = generate_team_memo(team_facts(team(), 0))
    assert report.outcome == "unavailable" and report.calls == []


def test_the_rule_based_memo_is_grounded_and_uses_only_real_commands():
    facts = team_facts(team(), anomaly_count=2)
    memo = rule_based_memo(facts)
    text = render_memo(memo)

    assert memo["focus"][0]["area"] == "cache"
    assert str(facts["team_size"]) in text and f"{facts['average_score']}" in text
    assert "2 days had unusual spend" in text
    assert unknown_commands(text) == [] and invented_files(text) == []


def test_the_prompt_lists_the_facts_and_the_allowed_commands(mock_gemini):
    reply(mock_gemini, memo_json())
    facts = team_facts(team(), 1)

    generate_team_memo(facts)

    prompt = mock_gemini.models.generate_content.call_args.kwargs["contents"]
    assert f"Average efficiency score: {facts['average_score']} / 100" in prompt
    assert ", ".join(COST_COMMANDS) in prompt


# ── The command guard itself ───────────────────────────────────────────────

@pytest.mark.parametrize("text, unknown", [
    ("Run /compact and /clear, check /context.", []),
    ("Try /claudedir or /optimize.", ["/claudedir", "/optimize"]),
    ("Spend was $13/day, see docs/en/costs and https://x.io/compact.", []),    # not commands
    ("Use /checkpoint (an alias of /rewind).", []),
])
def test_unknown_commands(text, unknown):
    assert unknown_commands(text) == unknown


def test_invented_files():
    assert invented_files("Create a .claudedir and a .clauderc file") == [".claudedir", ".clauderc"]
    assert invented_files("Edit CLAUDE.md or .claude/settings.json") == []


def test_the_cost_commands_are_real():
    assert set(COST_COMMANDS) <= KNOWN_COMMANDS


# ── Wiring: the digest and the CLI use the grounded memo, metered ───────────

def test_the_worker_sends_the_grounded_memo_and_meters_it(seeded_db, mock_gemini, monkeypatch, query):
    import data.alert_worker as worker

    reply(mock_gemini, memo_json())
    sent = {}
    monkeypatch.setattr(worker, "send_developer_alert", lambda dev, session=None: "sent")
    monkeypatch.setattr(worker, "send_daily_report", lambda **kw: sent.update(kw) or "sent")

    worker.run_weekly_telemetry_check()

    assert "steady spend" in sent["ai_summary"]
    row = query("SELECT outcome, prompt_version FROM ai_requests WHERE purpose = 'team_report'")[0]
    assert row == {"outcome": "ai", "prompt_version": TEAM_PROMPT_VERSION}


def test_latest_team_memo_without_data(empty_db):
    report = team_memo.latest_team_memo()
    assert report is None
