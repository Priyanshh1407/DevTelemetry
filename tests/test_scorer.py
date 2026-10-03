"""Efficiency score. Token fields follow Anthropic's usage semantics (ML-03a):
input_tokens = uncached prompt tokens; cache reads and cache writes are separate, so
total prompt = input + cache_read + cache_write and hit ratio = cache_read / total prompt.
"""
import random

import pytest

from core.scorer import POOL_DAYS, calculate_efficiency_score, score_breakdown, score_history

HAIKU_ONLY = {"haiku_pct": 1.0, "sonnet_pct": 0.0, "opus_pct": 0.0}
OPUS_ONLY = {"haiku_pct": 0.0, "sonnet_pct": 0.0, "opus_pct": 1.0}


def day(input_tokens, cache_read, cache_write=0, mix=HAIKU_ONLY, sessions=5, compacts=5):
    return {"input_tokens": input_tokens, "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
            "model_mix": mix, "session_count": sessions, "compact_uses": compacts}


def test_perfect_score_when_every_prompt_token_is_a_cache_read():
    assert calculate_efficiency_score(day(input_tokens=0, cache_read=100_000)) == 100.0


def test_poor_score():
    # no cache reads (0), all Opus (0.1 x 30 = 3), no /compact (0)
    assert calculate_efficiency_score(day(100_000, 0, mix=OPUS_ONLY, compacts=0)) == 3.0


def test_hit_ratio_counts_uncached_input_in_the_denominator():
    # half the prompt from cache: 0.5 x 40 = 20, Haiku 30, compact 30
    assert calculate_efficiency_score(day(input_tokens=50_000, cache_read=50_000)) == 80.0


def test_hit_ratio_counts_cache_writes_in_the_denominator():
    # Writes are prompt tokens that were NOT served from cache (they were processed, then stored).
    # Under the old formula (cache_read / input) this day scored the full 40 cache points.
    assert calculate_efficiency_score(day(input_tokens=0, cache_read=50_000, cache_write=50_000)) == 80.0


def test_zero_activity_does_not_divide_by_zero():
    # no prompt tokens -> 0 cache points; mix 0.5x1.0 + 0.5x0.6 = 0.8 -> 24; 0 sessions -> 0
    mix = {"haiku_pct": 0.5, "sonnet_pct": 0.5, "opus_pct": 0.0}
    assert calculate_efficiency_score(day(0, 0, mix=mix, sessions=0, compacts=2)) == 24.0


def test_accepts_flat_database_rows_as_well_as_nested_model_mix():
    nested = day(40_000, 60_000, cache_write=10_000)
    flat = {k: v for k, v in nested.items() if k != "model_mix"} | HAIKU_ONLY
    assert calculate_efficiency_score(flat) == calculate_efficiency_score(nested)


# ── ML-03b: discipline pooled over 7 days, normalized mix, breakdown ───────

def test_one_unlucky_day_does_not_wipe_out_a_steady_habit():
    # Uses /compact in half her sessions every day; today, by chance, in none of 2.
    steady = [day(0, 100_000, sessions=2, compacts=1) for _ in range(6)]
    unlucky_today = day(0, 100_000, sessions=2, compacts=0)

    daily_only = score_breakdown(unlucky_today)["discipline"]
    pooled = score_breakdown(unlucky_today, recent=steady)["discipline"]

    assert daily_only == 0.0
    assert pooled == round(6 / 14 * 30, 2)   # 6 compacts in 14 sessions over the week


def test_only_the_last_seven_days_count():
    old_perfect = [day(0, 1, sessions=4, compacts=4) for _ in range(20)]
    recent_none = [day(0, 1, sessions=4, compacts=0) for _ in range(POOL_DAYS - 1)]
    today = day(0, 1, sessions=4, compacts=0)

    assert score_breakdown(today, recent=old_perfect + recent_none)["discipline"] == 0.0


def test_score_history_uses_a_trailing_window():
    days = [day(0, 1, sessions=1, compacts=c) for c in (1, 1, 0)]
    scores = score_history(days)
    assert scores[0] == calculate_efficiency_score(days[0])
    assert scores[2] == calculate_efficiency_score(days[2], recent=days[:2])


def test_mix_shares_are_normalized_so_bad_data_cannot_exceed_100():
    over = day(0, 100_000, mix={"haiku_pct": 1.2, "sonnet_pct": 0.0, "opus_pct": 0.0})
    assert calculate_efficiency_score(over) == 100.0          # was 106.0 before normalization
    rounded = day(0, 0, mix={"haiku_pct": 0.33, "sonnet_pct": 0.33, "opus_pct": 0.33})
    exact = day(0, 0, mix={"haiku_pct": 1 / 3, "sonnet_pct": 1 / 3, "opus_pct": 1 / 3})
    assert calculate_efficiency_score(rounded) == calculate_efficiency_score(exact)


def test_breakdown_parts_add_up_to_the_score():
    b = score_breakdown(day(30_000, 60_000, cache_write=10_000, sessions=4, compacts=1))
    assert set(b) == {"cache", "model_mix", "discipline", "total"}
    assert b["total"] == pytest.approx(b["cache"] + b["model_mix"] + b["discipline"], abs=0.02)


# ── Property tests: invariants over many random inputs ─────────────────────

def random_day(rng):
    shares = [rng.random() for _ in range(3)]
    return day(rng.randint(0, 10**7), rng.randint(0, 10**7), rng.randint(0, 10**6),
               mix=dict(zip(("haiku_pct", "sonnet_pct", "opus_pct"), shares, strict=True)),
               sessions=rng.randint(0, 12), compacts=rng.randint(0, 15))


def test_score_is_always_between_0_and_100():
    rng = random.Random(1)
    for _ in range(2000):
        recent = [random_day(rng) for _ in range(rng.randint(0, 8))]
        assert 0.0 <= calculate_efficiency_score(random_day(rng), recent) <= 100.0


def test_serving_more_of_the_prompt_from_cache_never_lowers_the_score():
    rng = random.Random(2)
    for _ in range(2000):
        d = random_day(rng)
        moved = min(d["input_tokens"], rng.randint(1, 10**6))
        better = dict(d, input_tokens=d["input_tokens"] - moved, cache_read_tokens=d["cache_read_tokens"] + moved)
        assert calculate_efficiency_score(better) >= calculate_efficiency_score(d)


def test_using_compact_more_never_lowers_the_score():
    rng = random.Random(3)
    for _ in range(2000):
        d = random_day(rng)
        assert calculate_efficiency_score(dict(d, compact_uses=d["compact_uses"] + 1)) >= calculate_efficiency_score(d)
