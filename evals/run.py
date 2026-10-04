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


def run(pipeline, mode, profiles=None, recordings=RECORDINGS, results=RESULTS, pause_s=0.0):
    profiles = profiles if profiles is not None else load()
    rows = []
    for index, profile in enumerate(profiles):
        if mode == "live" and pause_s and index:
            time.sleep(pause_s)  # stay under the free tier's requests-per-minute limit
        path = _recording_path(recordings, pipeline, profile["id"])
        if mode == "replay":
            calls = json.loads(path.read_text(encoding="utf-8"))["calls"]
            with provider_override(ReplayProvider(calls)):
                result = generate(pipeline, profile)
        else:
            result = generate(pipeline, profile)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"calls": [c.__dict__ for c in result.calls]}, indent=1) + "\n",
                            encoding="utf-8")
        rows.append(evaluate(profile, pipeline, result))

    summary = summarize(rows)
    summary.update({"pipeline": pipeline, "mode": mode,
                    "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    results.mkdir(parents=True, exist_ok=True)
    (results / f"{pipeline}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n",
                                              encoding="utf-8")
    (results / f"{pipeline}.md").write_text(report(summary, rows), encoding="utf-8")
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
    args = parser.parse_args(argv)
    summary, _ = run(args.pipeline, args.mode, pause_s=args.pause)
    print(report(summary, []).split("## Per profile")[0])  # noqa: T201


if __name__ == "__main__":
    main()
