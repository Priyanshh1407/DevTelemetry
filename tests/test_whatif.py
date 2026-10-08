"""UPG-06: what-if savings, by re-pricing the engineer's real tokens under a target habit."""
import random

import pytest

from core.pricing import estimate_cost
from core.whatif import MAX_CACHE_HIT, reprice_day, savings_facts, team_targets, what_if


def day(hit=0.6, opus=0.4, prompt=10_000_000, write_share=0.04, output=150_000):
    write = int(prompt * write_share)
    read = int(prompt * hit)
    return {"input_tokens": prompt - read - write, "cache_read_tokens": read, "cache_write_tokens": write,
            "output_tokens": output, "opus_pct": opus, "sonnet_pct": round(0.8 - opus, 2), "haiku_pct": 0.2}


def actual_cost(d):
    return estimate_cost(d["input_tokens"], d["output_tokens"], d["cache_read_tokens"], d["cache_write_tokens"], d)


def random_days(seed, n=30):
    rng = random.Random(seed)
    return [day(hit=rng.uniform(0.3, 0.9), opus=round(rng.uniform(0.05, 0.6), 2),
                prompt=rng.randint(1_000_000, 20_000_000), write_share=rng.uniform(0.01, 0.06)) for _ in range(n)]


def test_no_change_reproduces_the_actual_cost():
    for d in random_days(1):
        assert reprice_day(d) == pytest.approx(actual_cost(d))


@pytest.mark.parametrize("seed", range(5))
def test_a_higher_cache_target_never_costs_more(seed):
    for d in random_days(seed):
        costs = [reprice_day(d, cache_hit=t / 100) for t in range(0, 98, 7)]
        assert all(b <= a + 1e-9 for a, b in zip(costs, costs[1:], strict=False))


@pytest.mark.parametrize("seed", range(5))
def test_less_opus_never_costs_more(seed):
    for d in random_days(seed):
        costs = [reprice_day(d, opus_pct=t / 100) for t in range(100, -1, -10)]
        assert all(b <= a + 1e-9 for a, b in zip(costs, costs[1:], strict=False))


def test_targets_only_ever_improve_a_habit():
    good = day(hit=0.9, opus=0.05)
    assert reprice_day(good, cache_hit=0.5, opus_pct=0.5) == pytest.approx(actual_cost(good))


def test_cache_writes_and_total_prompt_are_unchanged():
    # Only the split between uncached input and cache reads moves; writes can't become reads.
    d = day(hit=0.5, write_share=0.05)
    full = reprice_day(d, cache_hit=MAX_CACHE_HIT, detail=True)
    assert full["cache_write_tokens"] == d["cache_write_tokens"]
    assert (full["input_tokens"] + full["cache_read_tokens"] + full["cache_write_tokens"]
            == d["input_tokens"] + d["cache_read_tokens"] + d["cache_write_tokens"])
    assert full["input_tokens"] >= 0


def test_opus_moves_to_sonnet():
    d = reprice_day(day(opus=0.5), opus_pct=0.1, detail=True)
    assert d["opus_pct"] == pytest.approx(0.1) and d["sonnet_pct"] == pytest.approx(0.7) and d["haiku_pct"] == 0.2


def test_what_if_reports_each_lever_per_month():
    days = [day(hit=0.5, opus=0.5)] * 10

    result = what_if(days, cache_hit=0.8, opus_pct=0.1)

    current = 3 * sum(actual_cost(d) for d in days)                    # 10 days scaled to 30
    assert result["days"] == 10
    assert result["current_month_usd"] == pytest.approx(current, abs=0.01)
    cache, model, both = result["cache"], result["model"], result["combined"]
    assert 0 < cache["saving_month_usd"] and 0 < model["saving_month_usd"]
    assert both["saving_month_usd"] > max(cache["saving_month_usd"], model["saving_month_usd"])
    assert both["projected_month_usd"] == pytest.approx(current - both["saving_month_usd"], abs=0.02)


@pytest.mark.parametrize("bad", [{"cache_hit": 0.98}, {"cache_hit": -0.1}, {"opus_pct": 1.1}, {"opus_pct": -0.01}])
def test_invalid_targets_are_rejected(bad):
    with pytest.raises(ValueError):
        what_if([day()], **bad)


def test_what_if_needs_data():
    with pytest.raises(ValueError):
        what_if([])


def test_team_targets_are_the_top_quartile_habits():
    team = {f"e{i}": [day(hit=0.1 * i, opus=round(0.06 * i, 2))] for i in range(1, 10)}

    targets = team_targets(team)

    assert targets["cache_hit"] == pytest.approx(0.7, abs=0.005)      # 75th percentile of 0.1..0.9
    assert targets["opus_pct"] == pytest.approx(0.18, abs=0.005)      # 25th percentile of 0.06..0.54


def test_savings_facts_are_rounded_for_citing():
    facts = savings_facts([day(hit=0.5, opus=0.5)] * 7, {"cache_hit": 0.8, "opus_pct": 0.1})
    assert facts == {
        "window_days": 7,
        "cache_target_pct": 80.0,
        "saving_month_usd_cache": round(facts["saving_month_usd_cache"], 2),
        "opus_target_pct": 10.0,
        "saving_month_usd_model": round(facts["saving_month_usd_model"], 2),
    }
    assert facts["saving_month_usd_cache"] > 0 and facts["saving_month_usd_model"] > 0
