"""Token cost estimation from a dated, per-model price table.

Prices are Anthropic first-party API list prices in USD per million tokens.
Source: https://platform.claude.com/docs/en/about-claude/pricing (and the prompt-caching
page for cache multipliers), as of PRICE_TABLE_VERSION. Update the version when prices change.

Cache pricing: 5-minute cache writes cost 1.25x the input price. Cache reads cost 0.1x
input, except Claude Opus 5.5 whose cache reads are $0.20 (0.05x).

Token fields follow Anthropic's usage object: input_tokens = uncached prompt tokens
(`input_tokens`), cache_read_tokens = `cache_read_input_tokens`, cache_write_tokens =
`cache_creation_input_tokens`. Each kind is billed once, at its own price.

Assumption (the telemetry is per engineer per day, not per request):
- The day's tokens are split across models in proportion to the model mix
  (opus_pct / sonnet_pct / haiku_pct, normalized to sum to 1).
"""

PRICE_TABLE_VERSION = "2026-09-25"

PRICES = {
    "opus": {"model_id": "claude-opus-5-5", "input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "sonnet": {"model_id": "claude-sonnet-5-5", "input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    "haiku": {"model_id": "claude-haiku-4-5", "input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
}

PER_MILLION = 1_000_000


def estimate_cost(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model_mix):
    """Returns the estimated USD cost of one engineer-day of usage.

    model_mix: {"opus_pct": .., "sonnet_pct": .., "haiku_pct": ..}, shares of usage per model.
    Raises ValueError for negative token counts or an unusable mix.
    """
    tokens = {"input": input_tokens, "output": output_tokens,
              "cache_read": cache_read_tokens, "cache_write": cache_write_tokens}
    if any(v is None or v < 0 for v in tokens.values()):
        raise ValueError(f"Token counts must be non-negative: {tokens}")

    shares = {model: model_mix.get(f"{model}_pct", 0) or 0 for model in PRICES}
    if any(s < 0 for s in shares.values()):
        raise ValueError(f"Model mix shares must be non-negative: {model_mix}")
    total_share = sum(shares.values())
    if total_share <= 0:
        raise ValueError(f"Model mix must have at least one positive share: {model_mix}")

    cost = 0.0
    for model, share in shares.items():
        price = PRICES[model]
        model_cost = (input_tokens * price["input"]
                      + output_tokens * price["output"]
                      + cache_read_tokens * price["cache_read"]
                      + cache_write_tokens * price["cache_write"]) / PER_MILLION
        cost += (share / total_share) * model_cost
    return cost
