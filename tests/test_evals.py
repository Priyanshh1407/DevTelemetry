"""UPG-01 eval harness: the checks themselves are tested, then a replay run end to end."""
import json
from collections import Counter

import pytest

from ai.features import coaching_facts
from evals.checks import allowed_numbers, classify_area, extract_numbers, is_grounded
from evals.profiles import load
from evals.run import run


@pytest.mark.parametrize("text, numbers", [
    ("Only 30.0% of prompt tokens came from cache.", [30.0]),
    ("You spent $9.87 today across 13 of 28 sessions.", [9.87, 13, 28]),
    ("That is 1,250,000 tokens, or 1.2M; output was 600k.", [1_250_000, 1_200_000, 600_000]),
    ("Use /compact and Gemini-2.5 or prompt v2 with Haiku.", []),
])
def test_number_extraction(text, numbers):
    assert extract_numbers(text) == pytest.approx(numbers)


def test_grounding_allows_rounding_but_not_invented_numbers():
    allowed = {46.4, 9.87, 10_234_567.0}
    assert is_grounded(46, allowed)                 # 46% for 46.4%
    assert is_grounded(10, allowed)                 # $10 for $9.87
    assert is_grounded(10_200_000, allowed)         # 10.2M
    assert not is_grounded(60, allowed)             # e.g. an invented "save 60%"


def test_allowed_numbers_cover_facts_and_raw_values():
    profile = load()[0]
    allowed = allowed_numbers(profile["day"], profile["recent"])
    facts = coaching_facts(profile["day"], profile["recent"])

    assert facts["cache_hit_pct"] in allowed and facts["compact_rate_7d_pct"] in allowed
    assert float(profile["day"]["input_tokens"]) in allowed
    assert round(profile["day"]["opus_pct"] * 100, 1) in allowed


@pytest.mark.parametrize("text, area", [
    ("Only 12% of your prompt came from cache; reuse cached context.", "cache"),
    ("Opus handled most requests; default to Sonnet and use Haiku for tests.", "model_mix"),
    ("Run /compact between tasks to keep the context window small.", "discipline"),
    ("Write clearer commit messages.", None),
])
def test_area_classification(text, area):
    assert classify_area(text) == area


def test_profiles_cover_every_area_and_tier():
    profiles = load()
    assert len(profiles) == 30
    assert Counter(p["weakest_area"] for p in profiles) == {"cache": 10, "model_mix": 10, "discipline": 10}
    assert {p["severity"] for p in profiles} == {"low", "moderate", "critical"}
    for p in profiles:  # the label matches what the scorer computes
        assert coaching_facts(p["day"], p["recent"])["weakest_area"] == p["weakest_area"]
        assert "name" not in p["day"] and "email" not in p["day"]


def _call(text):
    return {"text": text, "model": "gemini-2.5-flash", "input_tokens": 800, "output_tokens": 400,
            "latency_ms": 1200, "cost_usd": 0.00124}


def test_replay_run_scores_recorded_guides(tmp_path):
    profiles = load()[:3]
    facts = coaching_facts(profiles[0]["day"], profiles[0]["recent"])
    good = json.dumps({"headline": "Fix caching first.", "actions": [
        {"title": "Reuse cache", "problem": f"Only {facts['cache_hit_pct']}% came from cache.",
         "fix": "Keep one session per task so cached context is reused.", "focus": "cache"},
        {"title": "Compact", "problem": f"/compact used in {facts['compact_rate_7d_pct']}% of sessions.",
         "fix": "Run /compact between tasks.", "focus": "discipline"},
    ]})
    hallucinated = good.replace("Keep one session per task", "This saves 60% of your bill; keep one session per task")
    recordings = {"p01": [_call(good)], "p02": [_call(hallucinated)], "p03": [_call("oops"), _call("oops")]}
    for pid, calls in recordings.items():
        path = tmp_path / "recordings" / "v2" / f"{pid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"calls": calls}), encoding="utf-8")
    # profile p02/p03 have other weakest areas; reuse p01's numbers only for p01's guide
    summary, rows = run("v2", "replay", profiles=profiles, recordings=tmp_path / "recordings",
                        results=tmp_path / "results")

    by_id = {r["id"]: r for r in rows}
    assert by_id["p01"]["valid"] and by_id["p01"]["fully_grounded"] and by_id["p01"]["targeted"]
    assert 60.0 in by_id["p02"]["ungrounded"]                 # the invented saving is caught
    assert by_id["p03"]["source"] == "invalid_output" and not by_id["p03"]["valid"]
    assert summary["valid_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert summary["llm_calls"] == 4 and summary["cost_usd"] == pytest.approx(4 * 0.00124)
    assert (tmp_path / "results" / "v2.md").exists()
