"""ML-01: cost is computed from token usage and model mix with a dated price table."""
import pytest

from core.pricing import PRICES, PRICE_TABLE_VERSION, estimate_cost

SONNET_ONLY = {"opus_pct": 0.0, "sonnet_pct": 1.0, "haiku_pct": 0.0}
HAIKU_ONLY = {"opus_pct": 0.0, "sonnet_pct": 0.0, "haiku_pct": 1.0}
M = 1_000_000


def test_price_table_is_dated_and_complete():
    assert PRICE_TABLE_VERSION
    for model in ("opus", "sonnet", "haiku"):
        assert set(PRICES[model]) == {"model_id", "input", "output", "cache_write", "cache_read"}


def test_uncached_input_and_output_at_list_price():
    # 1M uncached input at $2 + 1M output at $10
    assert estimate_cost(input_tokens=M, output_tokens=M, cache_read_tokens=0,
                         cache_write_tokens=0, model_mix=SONNET_ONLY) == pytest.approx(12.00)


def test_cached_input_is_billed_at_cache_read_price():
    # input_tokens includes cache reads: 1M input, all of it read from cache at $0.10/M
    assert estimate_cost(input_tokens=M, output_tokens=0, cache_read_tokens=M,
                         cache_write_tokens=0, model_mix=HAIKU_ONLY) == pytest.approx(0.10)


def test_mixed_models_hand_computed():
    # 200k input (100k cached), 40k output, 20k cache writes, split 50/50 Opus/Haiku.
    # Opus:  100k*$4 + 100k*$0.20 + 20k*$5 + 40k*$20     = 0.40 + 0.02 + 0.10 + 0.80   = 1.32
    # Haiku: 100k*$1 + 100k*$0.10 + 20k*$1.25 + 40k*$5   = 0.10 + 0.01 + 0.025 + 0.20  = 0.335
    cost = estimate_cost(input_tokens=200_000, output_tokens=40_000, cache_read_tokens=100_000,
                         cache_write_tokens=20_000,
                         model_mix={"opus_pct": 0.5, "sonnet_pct": 0.0, "haiku_pct": 0.5})
    assert cost == pytest.approx(0.5 * 1.32 + 0.5 * 0.335)


def test_opus_costs_more_than_haiku_for_same_usage():
    usage = dict(input_tokens=300_000, output_tokens=50_000, cache_read_tokens=100_000, cache_write_tokens=10_000)
    opus = estimate_cost(**usage, model_mix={"opus_pct": 1.0, "sonnet_pct": 0.0, "haiku_pct": 0.0})
    haiku = estimate_cost(**usage, model_mix=HAIKU_ONLY)
    assert opus == pytest.approx(4 * haiku, rel=0.2)


def test_mix_is_normalized_when_rounding_leaves_it_off_one():
    usage = dict(input_tokens=100_000, output_tokens=10_000, cache_read_tokens=0, cache_write_tokens=0)
    rounded = estimate_cost(**usage, model_mix={"opus_pct": 0.33, "sonnet_pct": 0.33, "haiku_pct": 0.33})
    exact = estimate_cost(**usage, model_mix={"opus_pct": 1 / 3, "sonnet_pct": 1 / 3, "haiku_pct": 1 / 3})
    assert rounded == pytest.approx(exact)


def test_cache_reads_above_input_never_produce_negative_cost():
    cost = estimate_cost(input_tokens=1_000, output_tokens=0, cache_read_tokens=5_000,
                         cache_write_tokens=0, model_mix=SONNET_ONLY)
    assert cost == pytest.approx(5_000 * 0.20 / M)


@pytest.mark.parametrize("kwargs", [
    dict(input_tokens=-1, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0, model_mix=SONNET_ONLY),
    dict(input_tokens=1, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
         model_mix={"opus_pct": 0, "sonnet_pct": 0, "haiku_pct": 0}),
    dict(input_tokens=1, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
         model_mix={"opus_pct": -0.5, "sonnet_pct": 1.5, "haiku_pct": 0}),
])
def test_invalid_usage_is_rejected(kwargs):
    with pytest.raises(ValueError):
        estimate_cost(**kwargs)


def test_seeded_cost_is_computed_from_usage(empty_db, query):
    from data.seed import generate_historical_data

    generate_historical_data(days_back=3, num_engineers=4)

    for row in query("SELECT * FROM usage_metrics"):
        expected = estimate_cost(
            input_tokens=row["input_tokens"], output_tokens=row["output_tokens"],
            cache_read_tokens=row["cache_read_tokens"], cache_write_tokens=row["cache_write_tokens"],
            model_mix={k: row[k] for k in ("opus_pct", "sonnet_pct", "haiku_pct")})
        assert row["estimated_cost_usd"] == pytest.approx(expected, abs=1e-4)
