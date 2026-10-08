"""Automated checks for one coaching guide. Rule-based on purpose: cheap, deterministic, and
the properties checked here (valid structure, real numbers, right focus) are mechanically
checkable. Tone and helpfulness would need human review or an LLM judge; not measured here.

Both pipelines (v1 = numbered plain text, v2 = structured JSON) are judged by the same
rules on the same text, so their numbers are comparable.
"""
import re

from ai.features import coaching_facts

# A number as written in prose: optional $, thousands separators, decimals, optional %, k, M
# or a scale word ("11.53 million").
# The lookbehinds skip digits glued to letters or dots ("v2") and names like "gemini-2.5",
# while still reading ranges such as "1-2 sessions".
_NUMBER = re.compile(r"(?<![\w.])(?<![A-Za-z]-)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*"
                     r"(%|[kKM](?![a-zA-Z])|thousand|million|billion)?")
_MULTIPLIERS = {"k": 1_000, "K": 1_000, "thousand": 1_000, "M": 1_000_000, "million": 1_000_000,
                "billion": 1_000_000_000}

AREA_KEYWORDS = {
    "cache": ("cache", "cached", "caching"),
    "model_mix": ("opus", "sonnet", "haiku", "model"),
    "discipline": ("/compact", "compact", "context window"),
}

EXPECTED_ACTIONS = {
    "v1": {"critical": 5, "moderate": 3, "low": 3},
    "v2": {"critical": 4, "moderate": 3, "low": 2},
    "v3": {"critical": 4, "moderate": 3, "low": 2},
}
SAVING_KEYS = ("saving_month_usd_cache", "saving_month_usd_model")


# Prose a number reader would otherwise split or misread: "11 dollars and 91 cents" (one
# amount, 11.91) and ordinal dates such as "March 31st" (not a metric).
_MONEY_WORDS = re.compile(r"\b(\d+) dollars?(?: and)? (\d{1,2}) cents?\b")
_ORDINAL = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\b")


def extract_numbers(text):
    text = _MONEY_WORDS.sub(lambda m: f"${m[1]}.{int(m[2]):02d}", text)
    text = _ORDINAL.sub(" ", text)
    numbers = []
    for whole, decimals, suffix in _NUMBER.findall(text):
        value = float(whole.replace(",", "") + (decimals or ""))
        numbers.append(value * _MULTIPLIERS.get(suffix, 1))
    return numbers


def allowed_numbers(day, recent, savings=None):
    """Every number a guide may legitimately cite: the facts given to v2 (and v3's computed
    savings), the raw values given to v1 (shares also as percentages), and the score maxima /
    7-day window / 30-day period the prompts mention."""
    facts = coaching_facts(day, recent, savings=savings)
    allowed = {100.0, 40.0, 30.0, 7.0}
    for value in facts.values():
        values = value.values() if isinstance(value, dict) else [value]
        if savings and value is savings:
            allowed.add(30.0)       # "per 30 days"
        allowed.update(float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    for key, value in day.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.add(float(value))
            if key.endswith("_pct"):
                allowed.add(round(value * 100, 1))
    return allowed


def is_grounded(number, allowed):
    """Matches an allowed value within rounding (e.g. 46% for 46.4%, $10 for $9.87, 10.2M)."""
    return any(abs(number - a) <= max(0.5, 0.005 * abs(a)) for a in allowed)


def is_derived(number, allowed):
    """Not cited from the inputs, but correct arithmetic on them: a ratio of two inputs, such as
    "28,000 output tokens per session" (168,173 / 6). Reported apart from ungrounded numbers so
    the table separates invented numbers from computed ones. Only values >= 10, from divisors
    >= 2, within 1%, to keep coincidental matches rare."""
    if number < 10:
        return False
    values = [a for a in allowed if a > 0]
    return any(abs(number - a / b) <= 0.01 * (a / b) for a in values for b in values if b >= 2 and a > b)


def classify_area(text):
    """Which score area a piece of advice is about, from its wording (None if none)."""
    lowered = text.lower()
    hits = {area: sum(lowered.count(k) for k in keywords) for area, keywords in AREA_KEYWORDS.items()}
    best = max(hits.values())
    if best == 0:
        return None
    tied = [area for area, n in hits.items() if n == best]
    return min(tied, key=lambda area: min(lowered.find(k) for k in AREA_KEYWORDS[area] if k in lowered))


def action_texts(pipeline, result):
    if pipeline != "v1" and result.guide:
        return [f"{a['title']}. {a['problem']} {a['fix']}" for a in result.guide["actions"]]
    return [t["desc"] for t in result.tasks]


def evaluate(profile, pipeline, result, savings=None):
    """Scores one guide. `result` is an ai.guide_generator.GuideResult; `savings` = the computed
    savings the v3 prompt was given (they count as grounded)."""
    day, recent, severity = profile["day"], profile["recent"], profile["severity"]
    if pipeline != "v1":
        valid = not result.is_fallback
        first_try = result.source == "ai"
    else:  # v1 "works" when the model produced a parseable numbered list
        valid = result.source == "ai" and bool(result.tasks) and result.tasks[0]["title"] != "AI Summary"
        first_try = valid

    texts = action_texts(pipeline, result) if valid else []
    allowed = allowed_numbers(day, recent, savings)
    numbers = [n for t in texts for n in extract_numbers(t)]
    ungrounded = [n for n in numbers if not is_grounded(n, allowed)]
    derived = [n for n in ungrounded if is_derived(n, allowed)]
    weakest = coaching_facts(day, recent)["weakest_area"]

    calls = result.calls
    extra = {}
    if savings is not None:
        # Did a guide quote a computed saving (when there was one to quote)?
        quotable = [savings[k] for k in SAVING_KEYS if savings[k] > 0]
        extra["saving_quotable"] = bool(quotable)
        extra["cites_saving"] = any(is_grounded(n, set(quotable)) for n in numbers) if quotable else False
    return {**extra,
        "id": profile["id"],
        "severity": severity,
        "weakest_area": weakest,
        "source": result.source,
        "valid": valid,
        "first_try_valid": first_try,
        "actions": len(texts),
        "action_count_ok": valid and len(texts) == EXPECTED_ACTIONS[pipeline][severity],
        "numbers_cited": len(numbers),
        "ungrounded": ungrounded,
        "derived": derived,                       # subset of ungrounded: correct arithmetic, not invented
        "fully_grounded": valid and not ungrounded,
        "first_action_area": classify_area(texts[0]) if texts else None,
        "targeted": bool(texts) and classify_area(texts[0]) == weakest,
        "llm_calls": len(calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "latency_ms": sum(c.latency_ms for c in calls),
        "cost_usd": sum(c.cost_usd for c in calls),
    }


def _rate(rows, key):
    return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else None


def _percentile(values, pct):
    values = sorted(values)
    if not values:
        return None
    return values[max(1, -(-pct * len(values) // 100)) - 1]


def summarize(rows):
    cited = sum(r["numbers_cited"] for r in rows)
    ungrounded = sum(len(r["ungrounded"]) for r in rows)
    derived = sum(len(r.get("derived", [])) for r in rows)
    valid_rows = [r for r in rows if r["valid"]]
    return {
        "profiles": len(rows),
        "valid_rate": _rate(rows, "valid"),
        "first_try_valid_rate": _rate(rows, "first_try_valid"),
        "targeted_rate": _rate(rows, "targeted"),
        "action_count_ok_rate": _rate(rows, "action_count_ok"),
        "fully_grounded_rate": _rate(valid_rows, "fully_grounded"),
        "numbers_cited": cited,
        "grounded_number_rate": round(1 - ungrounded / cited, 3) if cited else None,
        "ungrounded_numbers": ungrounded,
        "derived_numbers": derived,
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "mean_input_tokens": round(sum(r["input_tokens"] for r in rows) / len(rows)) if rows else None,
        "mean_output_tokens": round(sum(r["output_tokens"] for r in rows) / len(rows)) if rows else None,
        "latency_ms_p50": _percentile([r["latency_ms"] for r in rows if r["llm_calls"]], 50),
        "latency_ms_p95": _percentile([r["latency_ms"] for r in rows if r["llm_calls"]], 95),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        # v3 only (absent from v1/v2 so their published results stay comparable)
        **({"saving_cited_rate": _rate([r for r in valid_rows if r["saving_quotable"]], "cites_saving")}
           if rows and "cites_saving" in rows[0] else {}),
    }
