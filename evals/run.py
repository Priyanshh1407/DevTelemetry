"""Eval harness for the coaching guides (UPG-01).

    python -m evals.run --pipeline v2 --mode replay   # recorded responses: free, deterministic (CI)
    python -m evals.run --pipeline v1 --mode live     # real API calls; records the responses

Live mode spends API quota (it needs GEMINI_API_KEY) and overwrites the recordings for that
pipeline, so it is never run in CI. Replay mode re-runs the exact same checks on those
recordings, which makes a recorded live run reproducible by anyone, offline.
Results: evals/results/<pipeline>.md and .json.
"""
import argparse
import json
import pathlib
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import ai.guide_generator as generator
from ai.providers import LLMResponse
from core.queries import without_pii
from evals.checks import evaluate, summarize
from evals.profiles import load

ROOT = pathlib.Path(__file__).parent
RECORDINGS = ROOT / "recordings"
RESULTS = ROOT / "results"


class ReplayProvider:
    """Plays back recorded model replies in order, with their recorded usage and latency."""

    def __init__(self, calls):
        self._calls = list(calls)
        self.model = self._calls[0]["model"] if self._calls else "replay"

    def generate(self, prompt, json_schema=None):
        if not self._calls:
            raise RuntimeError("replay: more model calls than were recorded")
        call = self._calls.pop(0)
        if call.get("error"):
            raise generator.AIUnavailableError(call["error"])
        return LLMResponse(**{k: call[k] for k in ("text", "model", "input_tokens", "output_tokens",
                                                   "latency_ms", "cost_usd")})


@contextmanager
def provider_override(provider):
    original = generator.get_provider
    generator.get_provider = lambda: provider
    try:
        yield
    finally:
        generator.get_provider = original


def generate(pipeline, profile):
    day = without_pii(profile["day"])
    if pipeline == "v1":
        return generator.generate_efficiency_guide_v1(day, profile["severity"])
    return generator.generate_efficiency_guide(day, profile["severity"],
                                               recent=[without_pii(d) for d in profile["recent"]])


def _recording_path(recordings, pipeline, profile_id):
    return recordings / pipeline / f"{profile_id}.json"


# Provider capacity outcomes (nothing billed): worth waiting out in a live eval, because they
# say nothing about prompt quality. Backoff in seconds before each retry.
CAPACITY_SOURCES = ("rate_limited", "unavailable")
CAPACITY_BACKOFF_S = (30, 60)
# This many profiles in a row still failing after their retries means a quota is used up
# (e.g. the free tier's requests-per-day limit): stop instead of retrying every profile.
MAX_CAPACITY_FAILURES_IN_A_ROW = 3


class ProviderCapacityExhausted(RuntimeError):
    pass


def _has_recording(path):
    return path.exists() and bool(json.loads(path.read_text(encoding="utf-8"))["calls"])


def _replay(pipeline, profile, path):
    calls = json.loads(path.read_text(encoding="utf-8"))["calls"]
    with provider_override(ReplayProvider(calls)):
        return generate(pipeline, profile)


def _live(pipeline, profile, sleep):
    result = generate(pipeline, profile)
    for wait in CAPACITY_BACKOFF_S:
        if result.source not in CAPACITY_SOURCES:
            break
        sleep(wait)
        result = generate(pipeline, profile)
    return result


def run(pipeline, mode, profiles=None, recordings=RECORDINGS, results=RESULTS, pause_s=0.0,
        only_missing=False, sleep=time.sleep):
    """`only_missing` (live): replay profiles that already have a recorded reply, call the API
    only for the rest, so finishing an interrupted run never pays for the same profile twice."""
    profiles = profiles if profiles is not None else load()
    rows = []
    live_calls = failures_in_a_row = 0
    for profile in profiles:
        path = _recording_path(recordings, pipeline, profile["id"])
        if mode == "replay" or (only_missing and _has_recording(path)):
            result = _replay(pipeline, profile, path)
        else:
            if pause_s and live_calls:
                sleep(pause_s)  # stay under the provider's requests-per-minute limit
            live_calls += 1
            result = _live(pipeline, profile, sleep)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"calls": [c.__dict__ for c in result.calls]}, indent=1) + "\n",
                            encoding="utf-8")
            failures_in_a_row = failures_in_a_row + 1 if result.source in CAPACITY_SOURCES else 0
            if failures_in_a_row >= MAX_CAPACITY_FAILURES_IN_A_ROW:
                raise ProviderCapacityExhausted(
                    f"{failures_in_a_row} profiles in a row were rate-limited or unavailable after retries "
                    f"(stopped at {profile['id']}); the quota is probably used up. Replies so far are "
                    "recorded: re-run later with --only-missing to finish.")
        rows.append(evaluate(profile, pipeline, result))

    summary = summarize(rows)
    summary.update({"pipeline": pipeline, "mode": mode,
                    "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    # A subset gets its own file (e.g. v1-n10) so it is never mistaken for the full eval.
    name = pipeline if len(profiles) == len(load()) else f"{pipeline}-n{len(profiles)}"
    summary["profile_ids"] = [p["id"] for p in profiles]
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{name}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n",
                                          encoding="utf-8")
    (results / f"{name}.md").write_text(report(summary, rows), encoding="utf-8")
    return summary, rows


def _pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def report(summary, rows):
    lines = [
        f"# Eval: prompt {summary['pipeline']} ({summary['mode']}, {summary['run_at']})", "",
        "| Metric | Value |", "|---|---|",
        f"| Profiles | {summary['profiles']} |",
        f"| Valid guide | {_pct(summary['valid_rate'])} |",
        f"| Valid on first try | {_pct(summary['first_try_valid_rate'])} |",
        f"| First action targets the weakest area | {_pct(summary['targeted_rate'])} |",
        f"| Requested number of actions | {_pct(summary['action_count_ok_rate'])} |",
        f"| Numbers cited | {summary['numbers_cited']} |",
        f"| Cited numbers that are grounded | {_pct(summary['grounded_number_rate'])} |",
        f"| Ungrounded numbers (of which correct arithmetic on inputs) | "
        f"{summary['ungrounded_numbers']} ({summary['derived_numbers']}) |",
        f"| Valid guides with no ungrounded number | {_pct(summary['fully_grounded_rate'])} |",
        f"| Model calls | {summary['llm_calls']} |",
        f"| Mean tokens in / out per guide | {summary['mean_input_tokens']} / {summary['mean_output_tokens']} |",
        f"| Latency p50 / p95 (ms) | {summary['latency_ms_p50']} / {summary['latency_ms_p95']} |",
        f"| Cost (USD) | {summary['cost_usd']:.4f} |",
        "", "## Per profile", "",
        "| Profile | Tier | Weakest | Source | Valid | Targeted (first action) | Ungrounded numbers |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['severity']} | {r['weakest_area']} | {r['source']} | "
                     f"{'yes' if r['valid'] else 'no'} | {r['first_action_area'] or '-'}"
                     f"{' (yes)' if r['targeted'] else ''} | {', '.join(f'{n:g}' for n in r['ungrounded']) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate the coaching-guide pipelines.")
    parser.add_argument("--pipeline", choices=["v1", "v2"], required=True)
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="seconds between profiles in live mode (free-tier rate limits)")
    parser.add_argument("--only-missing", action="store_true",
                        help="live mode: replay profiles already recorded, call the API only for the rest")
    parser.add_argument("--profiles", help="comma-separated profile ids to run (default: all 30)")
    args = parser.parse_args(argv)
    profiles = load()
    if args.profiles:
        wanted = args.profiles.split(",")
        unknown = set(wanted) - {p["id"] for p in profiles}
        if unknown:
            parser.error(f"unknown profile ids: {', '.join(sorted(unknown))}")
        profiles = [p for p in profiles if p["id"] in wanted]
    try:
        summary, _ = run(args.pipeline, args.mode, profiles=profiles, pause_s=args.pause,
                         only_missing=args.only_missing)
    except ProviderCapacityExhausted as e:
        raise SystemExit(f"Stopped: {e}") from e
    print(report(summary, []).split("## Per profile")[0])  # noqa: T201


if __name__ == "__main__":
    main()
