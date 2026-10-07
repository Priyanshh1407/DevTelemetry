"""UPG-08: the team-memo eval set and harness (live runs only with approval; CI replays)."""
import json
from collections import Counter

import pytest

import evals.team_run as runner
from ai.guide_generator import TeamReport
from ai.providers import LLMResponse
from ai.team_memo import team_facts
from evals.team_profiles import load

MEMO = json.dumps({"summary": "The team of 10 is steady this week with room to improve on caching.",
                   "focus": [{"area": "cache", "why": "Caching loses the most points across the team.",
                              "practice": "Keep one session per task and run /compact between sub-tasks."}]})


def test_profiles_cover_every_area_and_anomaly_count():
    profiles = load()
    assert len(profiles) == 15
    assert Counter(p["biggest_area"] for p in profiles) == {"cache": 5, "model_mix": 5, "discipline": 5}
    assert {p["anomaly_count"] for p in profiles} == {0, 1, 2, 3}
    for p in profiles:
        assert team_facts(p["team"], p["anomaly_count"])["biggest_area"] == p["biggest_area"]


@pytest.mark.parametrize("pipeline, reply", [("team-v1", "All good.\n\nUse /compact more."), ("team-v2", MEMO)])
def test_live_records_and_replay_reproduces(tmp_path, mock_gemini, pipeline, reply):
    mock_gemini.models.generate_content.return_value.text = reply
    profiles = load()[:2]

    live, _ = runner.run(pipeline, "live", profiles=profiles, recordings=tmp_path / "rec",
                         results=tmp_path / "live", sleep=lambda s: None)
    replay, _ = runner.run(pipeline, "replay", profiles=profiles, recordings=tmp_path / "rec",
                           results=tmp_path / "replay")

    assert live["valid_rate"] == 1.0
    volatile = {"run_at", "mode"}
    assert {k: v for k, v in live.items() if k not in volatile} == \
           {k: v for k, v in replay.items() if k not in volatile}
    models = {c.kwargs["model"] for c in mock_gemini.models.generate_content.call_args_list}
    assert models == {runner.EVAL_MODEL}                       # one model, never the fallback


def response(text):
    return LLMResponse(text=text, model="m", input_tokens=1, output_tokens=1, latency_ms=1, cost_usd=0.0)


def test_invented_commands_are_counted_in_the_first_reply_and_in_what_the_manager_reads():
    profile = load()[0]
    facts = team_facts(profile["team"], profile["anomaly_count"])
    v1 = TeamReport(text="Fine.\n\nCreate a .claudedir and run /optimize daily.", outcome="ai",
                    calls=[response("Fine.\n\nCreate a .claudedir and run /optimize daily.")])

    row = runner.evaluate(profile, "team-v1", v1)

    assert row["first_reply_invented"] == ["/optimize", ".claudedir"] == row["final_invented"]
    repaired = TeamReport(text="Use /compact.", outcome="ai_repaired",
                          calls=[response("run /optimize"), response(MEMO)],
                          memo={"summary": "s", "focus": [{"area": facts["biggest_area"], "why": "w", "practice": "p"}]})
    assert runner.evaluate(profile, "team-v2", repaired)["final_invented"] == []
    assert runner.evaluate(profile, "team-v2", repaired)["first_reply_invented"] == ["/optimize"]


def test_numbers_are_checked_against_the_team_facts():
    profile = load()[0]
    facts = team_facts(profile["team"], profile["anomaly_count"])
    text = f"The team averaged {facts['average_score']} and spent $999.99.\n\nFocus on caching."
    row = runner.evaluate(profile, "team-v1", TeamReport(text=text, outcome="ai", calls=[response(text)]))
    assert row["ungrounded"] == [999.99]
