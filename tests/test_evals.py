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
    ("Cache reads were 11.53 million vs 1.24 billion; 3 thousand runs.", [11_530_000, 1_240_000_000, 3_000]),
    ("It cost 11 dollars and 91 cents, or 8 dollar 11 cent yesterday.", [11.91, 8.11]),   # money in words
    ("No compacts on March 31st or the 2nd; 3 sessions.", [3]),                            # dates aren't metrics
])
def test_number_extraction(text, numbers):
    assert extract_numbers(text) == pytest.approx(numbers)


def test_grounding_allows_rounding_but_not_invented_numbers():
    allowed = {46.4, 9.87, 10_234_567.0}
    assert is_grounded(46, allowed)                 # 46% for 46.4%
    assert is_grounded(10, allowed)                 # $10 for $9.87
    assert is_grounded(10_200_000, allowed)         # 10.2M
    assert not is_grounded(60, allowed)             # e.g. an invented "save 60%"


def test_correct_arithmetic_on_the_inputs_is_derived_not_invented():
    from evals.checks import is_derived

    allowed = {168_173.0, 6.0, 9.87}
    assert is_derived(28_000, allowed)        # 168,173 output tokens / 6 sessions, rounded
    assert not is_derived(60, allowed)        # the invented "save 60%" stays unexplained


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
    return {"text": text, "model": "gemini-3.8-flash", "input_tokens": 800, "output_tokens": 400,
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
        path = tmp_path / "recordings" / "gemini-3.8-flash" / "v2" / f"{pid}.json"
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
    assert (tmp_path / "results" / "gemini-3.8-flash" / "v2-n3.md").exists()


def test_live_retries_capacity_errors_and_only_missing_skips_recorded_profiles(tmp_path, mock_gemini):
    from google.genai import errors

    import evals.run as runner

    profiles = load()[:2]
    good = _call(json.dumps({"headline": "Fix caching first.", "actions": [
        {"title": "Reuse cache", "problem": "Cache hits are low today.", "fix": "Keep one session per task.",
         "focus": "cache"}]}))
    recorded = tmp_path / "recordings" / "gemini-3.8-flash" / "v2" / "p01.json"
    recorded.parent.mkdir(parents=True)
    recorded.write_text(json.dumps({"calls": [good]}), encoding="utf-8")

    rate_limited = errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    ok = type(mock_gemini.models.generate_content.return_value)()
    ok.text = good["text"]
    ok.usage_metadata.prompt_token_count = 10
    ok.usage_metadata.candidates_token_count = 10
    ok.usage_metadata.thoughts_token_count = 0
    mock_gemini.models.generate_content.side_effect = [rate_limited, ok]
    waits = []

    summary, rows = runner.run("v2", "live", profiles=profiles, recordings=tmp_path / "recordings",
                               results=tmp_path / "results", only_missing=True, sleep=waits.append)

    assert mock_gemini.models.generate_content.call_count == 2   # p01 replayed; p02 rate-limited once, then ok
    assert waits == [30]
    assert [r["source"] for r in rows] == ["ai", "ai"]


def test_live_run_stops_when_the_quota_is_used_up(tmp_path, mock_gemini):
    from google.genai import errors

    import evals.run as runner

    quota = errors.ClientError(429, {"error": {"code": 429, "message": "per day", "status": "RESOURCE_EXHAUSTED"}})
    mock_gemini.models.generate_content.side_effect = quota

    with pytest.raises(runner.ProviderCapacityExhausted, match="--only-missing"):
        runner.run("v2", "live", profiles=load()[:10], recordings=tmp_path / "rec", results=tmp_path / "res",
                   sleep=lambda s: None)

    # 3 profiles x (1 try + 2 retries), then it stops instead of working through all 10
    assert mock_gemini.models.generate_content.call_count == 9
    assert not (tmp_path / "res").exists()   # no half-baked results table


def test_a_subset_run_is_labelled_with_its_size(tmp_path):
    profiles = load()[:2]
    for p in profiles:
        path = tmp_path / "rec" / "gemini-3.8-flash" / "v2" / f"{p['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"calls": [_call("not json"), _call("still not json")]}), encoding="utf-8")

    summary, _ = run("v2", "replay", profiles=profiles, recordings=tmp_path / "rec", results=tmp_path / "res")

    out = tmp_path / "res" / "gemini-3.8-flash"
    assert (out / "v2-n2.md").exists() and not (out / "v2.md").exists()
    assert summary["profile_ids"] == ["p01", "p02"]


def test_a_live_eval_uses_one_model_and_never_the_fallback(tmp_path, mock_gemini):
    from google.genai import errors

    import evals.run as runner

    quota = errors.ClientError(429, {"error": {"code": 429, "message": "q", "status": "RESOURCE_EXHAUSTED"}})
    mock_gemini.models.generate_content.side_effect = quota

    with pytest.raises(runner.ProviderCapacityExhausted):
        runner.run("v2", "live", profiles=load()[:3], recordings=tmp_path / "rec", results=tmp_path / "res",
                   sleep=lambda s: None, model="gemini-3.5-flash-lite")

    models = {c.kwargs["model"] for c in mock_gemini.models.generate_content.call_args_list}
    assert models == {"gemini-3.5-flash-lite"}
    assert (tmp_path / "rec" / "gemini-3.5-flash-lite" / "v2" / "p01.json").exists()
