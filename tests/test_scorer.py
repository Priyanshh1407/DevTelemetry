"""Efficiency score. Token fields follow Anthropic's usage semantics (ML-03a):
input_tokens = uncached prompt tokens; cache reads and cache writes are separate, so
total prompt = input + cache_read + cache_write and hit ratio = cache_read / total prompt.
"""
from core.scorer import calculate_efficiency_score

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
