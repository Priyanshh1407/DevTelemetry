"""Eval harness for the manager's team memo (UPG-08): team-v1 (the old free-text memo) vs team-v2.

    python -m evals.team_run --pipeline team-v2 --mode replay   # recorded replies (CI)
    python -m evals.team_run --pipeline team-v1 --mode live     # real API calls; records them

Same conventions as evals/run.py: one model per run (no fallback), recordings and results per
model, capacity backoff, --only-missing to finish an interrupted live run.

Both pipelines are judged by the same rules on their final text:
- valid: team-v1 = the model answered; team-v2 = a schema-valid memo with real commands only;
- grounded: every number matches a team fact (or a constant the prompts state);
- targeted: the recommendations are mostly about the team's biggest gap
  (team-v1: its last paragraph; team-v2: its focus areas);
- invented commands/files: in the model's FIRST reply (what the model does on its own) and in
  the final text (what a manager would read).
"""
import argparse
import json
import time
from datetime import datetime, timezone

import ai.guide_generator as generator
import ai.team_memo as team_memo
from ai.claude_code import invented_files, unknown_commands
from ai.providers import GeminiProvider
from evals.checks import _percentile, _rate, classify_area, extract_numbers, is_derived, is_grounded
from evals.run import (CAPACITY_BACKOFF_S, EVAL_MODEL, MAX_CAPACITY_FAILURES_IN_A_ROW, RECORDINGS, RESULTS,
                       ProviderCapacityExhausted, ReplayProvider, _has_recording, _pct, _same_numbers)
from evals.team_profiles import load

PIPELINES = ("team-v1", "team-v2")
CAPACITY_OUTCOMES = ("rate_limited", "unavailable")
# Numbers the prompts themselves state: score maxima, "2-3 sentences", "1 or 2 focus areas", 7 days.
PROMPT_CONSTANTS = {1.0, 2.0, 3.0, 7.0, 30.0, 40.0, 100.0}


def _override(provider):
    originals = generator.get_provider, team_memo.get_provider
    generator.get_provider = team_memo.get_provider = lambda: provider
    return originals


def _restore(originals):
    generator.get_provider, team_memo.get_provider = originals


def generate(pipeline, profile):
    facts = team_memo.team_facts(profile["team"], profile["anomaly_count"])
    if pipeline == "team-v1":
        # The old worker's input: three aggregates.
        return generator.generate_team_report({"average_score": facts["average_score"],
                                               "total_spend": facts["total_cost_usd"],
                                               "critical_count": facts["critical_count"]})
    return team_memo.generate_team_memo(facts)


def allowed_numbers(facts):
    allowed = set(PROMPT_CONSTANTS)
    for value in facts.values():
        values = value.values() if isinstance(value, dict) else [value]
        allowed.update(float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    return allowed


def recommendations(pipeline, report):
    if pipeline == "team-v2":
        return " ".join(f"{f['why']} {f['practice']}" for f in (report.memo or {}).get("focus", []))
    paragraphs = [p for p in report.text.split("\n\n") if p.strip()]
    return paragraphs[-1] if paragraphs else ""


def evaluate(profile, pipeline, report):
    facts = team_memo.team_facts(profile["team"], profile["anomaly_count"])
    valid = report.outcome in ("ai", "ai_repaired") and bool(report.text.strip())
    text = report.text if valid else ""
    numbers = extract_numbers(text)
    allowed = allowed_numbers(facts)
    ungrounded = [n for n in numbers if not is_grounded(n, allowed)]
    first_reply = report.calls[0].text if report.calls else ""
    area = classify_area(recommendations(pipeline, report)) if valid else None
    calls = report.calls
    return {
        "id": profile["id"], "biggest_area": facts["biggest_area"], "outcome": report.outcome,
        "valid": valid, "first_try_valid": report.outcome == "ai",
        "numbers_cited": len(numbers), "ungrounded": ungrounded,
        "derived": [n for n in ungrounded if is_derived(n, allowed)],
        "fully_grounded": valid and not ungrounded,
        "recommendation_area": area, "targeted": area == facts["biggest_area"],
        "first_reply_invented": unknown_commands(first_reply) + invented_files(first_reply),
        "final_invented": unknown_commands(text) + invented_files(text),
        "llm_calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls), "latency_ms": sum(c.latency_ms for c in calls),
        "cost_usd": sum(c.cost_usd for c in calls),
    }


def summarize(rows):
    cited = sum(r["numbers_cited"] for r in rows)
    ungrounded = sum(len(r["ungrounded"]) for r in rows)
    valid = [r for r in rows if r["valid"]]
    answered = [r for r in rows if r["llm_calls"]]
    return {
        "profiles": len(rows), "valid_rate": _rate(rows, "valid"),
        "first_try_valid_rate": _rate(rows, "first_try_valid"), "targeted_rate": _rate(rows, "targeted"),
        "numbers_cited": cited, "grounded_number_rate": round(1 - ungrounded / cited, 3) if cited else None,
        "ungrounded_numbers": ungrounded, "derived_numbers": sum(len(r["derived"]) for r in rows),
        "fully_grounded_rate": _rate(valid, "fully_grounded"),
        "first_reply_invented_rate": (round(sum(bool(r["first_reply_invented"]) for r in answered) / len(answered), 3)
                                      if answered else None),
        "final_invented": sum(len(r["final_invented"]) for r in rows),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "mean_input_tokens": round(sum(r["input_tokens"] for r in rows) / len(rows)) if rows else None,
        "mean_output_tokens": round(sum(r["output_tokens"] for r in rows) / len(rows)) if rows else None,
        "latency_ms_p50": _percentile([r["latency_ms"] for r in answered], 50),
        "latency_ms_p95": _percentile([r["latency_ms"] for r in answered], 95),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
    }


def _recording(recordings, model, pipeline, profile_id):
    return recordings / model / pipeline / f"{profile_id}.json"


def run(pipeline, mode, profiles=None, recordings=RECORDINGS, results=RESULTS, pause_s=0.0, only_missing=False,
        sleep=time.sleep, model=EVAL_MODEL):
    profiles = profiles if profiles is not None else load()
    rows, live_calls, failures_in_a_row = [], 0, 0
    for profile in profiles:
        path = _recording(recordings, model, pipeline, profile["id"])
        if mode == "replay" or (only_missing and _has_recording(path)):
            originals = _override(ReplayProvider(json.loads(path.read_text(encoding="utf-8"))["calls"]))
            try:
                report = generate(pipeline, profile)
            finally:
                _restore(originals)
        else:
            if pause_s and live_calls:
                sleep(pause_s)
            live_calls += 1
            originals = _override(GeminiProvider(model, fallback_model=None))
            try:
                report = generate(pipeline, profile)
                for wait in CAPACITY_BACKOFF_S:
                    if report.outcome not in CAPACITY_OUTCOMES:
                        break
                    sleep(wait)
                    report = generate(pipeline, profile)
            finally:
                _restore(originals)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"calls": [c.__dict__ for c in report.calls]}, indent=1) + "\n",
                            encoding="utf-8")
            failures_in_a_row = failures_in_a_row + 1 if report.outcome in CAPACITY_OUTCOMES else 0
            if failures_in_a_row >= MAX_CAPACITY_FAILURES_IN_A_ROW:
                raise ProviderCapacityExhausted(
                    f"{failures_in_a_row} profiles in a row were rate-limited or unavailable (stopped at "
                    f"{profile['id']}); re-run later with --only-missing.")
        rows.append(evaluate(profile, pipeline, report))

    summary = summarize(rows)
    summary.update({"pipeline": pipeline, "mode": mode, "model": model,
                    "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "profile_ids": [p["id"] for p in profiles]})
    name = pipeline if len(profiles) == len(load()) else f"{pipeline}-n{len(profiles)}"
    out = results / model
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{name}.json"
    if mode == "replay" and _same_numbers(json_path, summary, rows):
        return summary, rows
    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    (out / f"{name}.md").write_text(report_md(summary, rows), encoding="utf-8")
    return summary, rows


def report_md(summary, rows):
    lines = [
        f"# Eval: team memo {summary['pipeline']} on {summary['model']}", "",
        f"Replies: live API calls, recorded in `evals/recordings/{summary['model']}/{summary['pipeline']}/`. "
        f"Scored {summary['run_at']} ({'during the live run' if summary['mode'] == 'live' else 'from the recordings'}).",
        "", "| Metric | Value |", "|---|---|",
        f"| Team-day profiles | {summary['profiles']} |",
        f"| Valid memo | {_pct(summary['valid_rate'])} |",
        f"| Valid on first try | {_pct(summary['first_try_valid_rate'])} |",
        f"| Recommendations target the team's biggest gap | {_pct(summary['targeted_rate'])} |",
        f"| Numbers cited | {summary['numbers_cited']} |",
        f"| Cited numbers that are grounded | {_pct(summary['grounded_number_rate'])} |",
        f"| Ungrounded numbers (of which correct arithmetic on inputs) | "
        f"{summary['ungrounded_numbers']} ({summary['derived_numbers']}) |",
        f"| Valid memos with no ungrounded number | {_pct(summary['fully_grounded_rate'])} |",
        f"| First replies inventing a command or file | {_pct(summary['first_reply_invented_rate'])} |",
        f"| Invented commands/files in what the manager reads | {summary['final_invented']} |",
        f"| Model calls | {summary['llm_calls']} |",
        f"| Mean tokens in / out per memo | {summary['mean_input_tokens']} / {summary['mean_output_tokens']} |",
        f"| Latency p50 / p95 (ms) | {summary['latency_ms_p50']} / {summary['latency_ms_p95']} |",
        f"| Cost (USD) | {summary['cost_usd']:.4f} |",
        "", "## Per profile", "",
        "| Profile | Biggest gap | Outcome | Valid | Recommendations about | Ungrounded numbers | Invented (first reply) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['biggest_area']} | {r['outcome']} | {'yes' if r['valid'] else 'no'} | "
                     f"{r['recommendation_area'] or '-'}{' (yes)' if r['targeted'] else ''} | "
                     f"{', '.join(f'{n:g}' for n in r['ungrounded']) or '-'} | "
                     f"{', '.join(r['first_reply_invented']) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate the team memo pipelines.")
    parser.add_argument("--pipeline", choices=PIPELINES, required=True)
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between profiles in live mode")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--model", default=EVAL_MODEL)
    args = parser.parse_args(argv)
    try:
        summary, _ = run(args.pipeline, args.mode, pause_s=args.pause, only_missing=args.only_missing,
                         model=args.model)
    except ProviderCapacityExhausted as e:
        raise SystemExit(f"Stopped: {e}") from e
    print(report_md(summary, []).split("## Per profile")[0])  # noqa: T201


if __name__ == "__main__":
    main()
