"""Database access for AI features: the coaching-guide store (UPG-01) and request metering (UPG-04)."""
import json
from datetime import datetime, timedelta, timezone

FALLBACK_OUTCOMES = ("invalid_output", "rate_limited", "unavailable")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Coaching-guide store ────────────────────────────────────────────────────

def load_guide(conn, user_id, metrics_date, severity, prompt_version, model):
    row = conn.execute("""
        SELECT guide_json FROM coaching_guides
        WHERE user_id = ? AND metrics_date = ? AND severity = ? AND prompt_version = ? AND model = ?
    """, (user_id, metrics_date, severity, prompt_version, model)).fetchone()
    return json.loads(row["guide_json"]) if row else None


def save_guide(conn, user_id, metrics_date, severity, prompt_version, model, source, guide):
    # OR IGNORE: two requests that generated the same guide concurrently both succeed; one row is kept.
    conn.execute("""
        INSERT OR IGNORE INTO coaching_guides
            (user_id, metrics_date, severity, prompt_version, model, source, guide_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, metrics_date, severity, prompt_version, model, source, json.dumps(guide), _now()))


# ── Metering ────────────────────────────────────────────────────────────────

def record_request(conn, purpose, outcome, calls=(), user_id=None, model=None, prompt_version=None):
    """One row per AI request handled; `calls` are the LLMResponses the request made (may be none)."""
    calls = list(calls)
    conn.execute("""
        INSERT INTO ai_requests (created_at, purpose, user_id, outcome, model, prompt_version, llm_calls,
                                 input_tokens, output_tokens, latency_ms, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (_now(), purpose, user_id, outcome, model, prompt_version, len(calls),
          sum(c.input_tokens for c in calls), sum(c.output_tokens for c in calls),
          sum(c.latency_ms for c in calls), round(sum(c.cost_usd for c in calls), 6)))


def _percentile(sorted_values, pct):
    """Nearest-rank percentile; None for no data."""
    if not sorted_values:
        return None
    rank = max(1, -(-pct * len(sorted_values) // 100))  # ceil(pct/100 * n), at least 1
    return sorted_values[int(rank) - 1]


def ai_stats(conn, purpose="guide", days=30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM ai_requests WHERE purpose = ? AND created_at >= ?", (purpose, since))]

    by_outcome = {}
    for r in rows:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    generated = [r for r in rows if r["outcome"] != "cache_hit"]
    with_calls = [r for r in rows if r["llm_calls"] > 0]
    latencies = sorted(r["latency_ms"] for r in with_calls)
    cost = round(sum(r["cost_usd"] for r in rows), 6)

    return {
        "purpose": purpose,
        "window_days": days,
        "requests": len(rows),
        "by_outcome": by_outcome,
        "cache_hit_rate": round(by_outcome.get("cache_hit", 0) / len(rows), 4) if rows else None,
        # Share of requests that needed generation but ended on the rule-based guide.
        "fallback_rate": (sum(1 for r in generated if r["outcome"] in FALLBACK_OUTCOMES) / len(generated)
                          if generated else None),
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "tokens": {"input": sum(r["input_tokens"] for r in rows), "output": sum(r["output_tokens"] for r in rows)},
        "cost_usd": cost,
        "cost_per_generated_guide_usd": round(cost / len(with_calls), 6) if with_calls else None,
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
    }
