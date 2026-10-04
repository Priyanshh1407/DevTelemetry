# How the efficiency score works

Each engineer gets a score from 0 to 100 for each day (`core/scorer.py`). It rewards three habits that drive the cost of AI coding tools, rather than raw spend: a heavy user with good habits outscores a light user with bad ones.

| Part | Points | Measures | How |
|---|---|---|---|
| Cache | 40 | How much of the prompt was served from cache | `cache_read / (input + cache_read + cache_write)` × 40 |
| Model mix | 30 | Use of cheaper models | weighted share: Haiku 1.0, Sonnet 0.6, Opus 0.1 (shares normalized to sum to 1) × 30 |
| Discipline | 30 | Context management | `/compact` uses ÷ sessions, **pooled over the last 7 days**, capped at 1 × 30 |

`GET /api/engineer/{id}/details` returns the parts for the latest day as `latest.score_breakdown`.

## Token fields

The fields mean the same as in Anthropic's API `usage` object, so real usage data maps field for field:

| Column | Anthropic usage field | Meaning |
|---|---|---|
| `input_tokens` | `input_tokens` | uncached prompt tokens |
| `cache_read_tokens` | `cache_read_input_tokens` | prompt tokens served from cache |
| `cache_write_tokens` | `cache_creation_input_tokens` | prompt tokens processed and written to cache |
| `output_tokens` | `output_tokens` | generated tokens |

Cache writes count as misses in the hit ratio: those tokens were processed in full (then stored), not read.

Cost (`core/pricing.py`) bills each kind once at its own list price (dated price table). The day's tokens are split across models by the model-mix shares.

## Why these choices

- **Habits, not spend.** Cost depends mostly on how much someone works. The score asks whether that work is done efficiently, so it doesn't punish productive engineers.
- **Weights (40/30/30, model weights 1.0/0.6/0.1) are judgment calls**, not learned from data. There is no ground-truth label of an "efficient engineer" to learn them from. So how much the leaderboard depends on them is measured (see below).
- **The discipline term is pooled over 7 days.** A single day has only 2–7 sessions, so the daily ratio was mostly luck: the same habit gives 0/2, 1/2 or 2/2. That one term carried almost all day-to-day rank noise (within-engineer daily SD 7.1 points vs 1.6 for cache and 0.7 for model mix). Because the bottom 2 get "critical" alerts, that noise meant unfair alerts. Pooling 7 days measures the habit:
  - daily SD 7.07 → 2.44 points;
  - the bottom 2 match the habitually worst engineers 82% of the time (median over 30 simulated teams), up from 65%.
  - **Cost:** a real change in habit takes about a week to show fully.

## How much do the weights matter?

`python -m analysis.weight_sensitivity` simulates 30 teams of 10 engineers (persona model, in memory). It ranks each team's latest day with the real weights, then again with one area weight moved by ±20%:

| Weights | Mean Kendall τ | Worst team | Bottom 2 unchanged |
|---|---|---|---|
| baseline (40/30/30) | 1.000 | 1.000 | 100% |
| cache −20% (32) | 0.933 | 0.733 | 90% |
| cache +20% (48) | 0.941 | 0.778 | 83% |
| model mix −20% (24) | 0.976 | 0.867 | 93% |
| model mix +20% (36) | 0.969 | 0.867 | 93% |
| discipline −20% (24) | 0.929 | 0.733 | 90% |
| discipline +20% (36) | 0.942 | 0.778 | 93% |

Kendall τ is rank agreement: 1.0 is the same order, 0 is unrelated.

- **The ordering is robust:** τ stays at 0.93–0.98.
- **The "critical" boundary is less certain:** in about 1 team in 10 (up to 17% when the cache weight rises), a 20% change in one weight swaps who is in the bottom 2.
- **So "critical" is a prompt for a conversation, not a verdict,** especially for engineers close to the boundary.

## Severity tiers

Severity is relative to the team on the latest day (`core/severity.py`): the top 5 are `low`, the bottom 2 are `critical`, and everyone in between is `moderate`.

Engineers without data on the latest day are not ranked. In a team of 6 or fewer, "low" takes priority, so nobody is `critical`. This is a known quirk, kept deliberately and tested.

## Known limitations

- **The model mix ignores task difficulty.** Using Haiku for everything, including architecture work, earns full points. The data has no task-complexity signal, so "Opus on simple tasks" can't be distinguished from "Opus on hard tasks".
- **Goodhart's law.** Once people know `/compact` is scored, they can game it (compacting needlessly). Treat the score as a conversation starter, not a performance metric.
- **No outcome measure.** `git_commits` is collected but not scored. The score measures how tokens are used, not what was delivered.
- **The data is simulated.** Engineers are personas with stable habits plus daily noise, calibrated to Anthropic's published Claude Code cost (~$13 per developer per active day, under $30 for 90% of users). Real telemetry ingestion is planned (UPG-02).
- **Cost is split across models by share of usage**, not by real per-request token counts, because the data is a daily aggregate.

## Changing the formula

Bump `SCORING_VERSION` in `core/scorer.py`. On the next startup, `init_db()` recomputes every stored score with the new formula, on the same trailing windows, and records the version in `schema_meta`. The tests in `tests/test_scorer.py` (including property tests over random inputs) and `tests/test_migrations.py` cover both parts.

| Version | Change |
|---|---|
| 2 | Token fields aligned with Anthropic's `usage` semantics; cache writes count as misses |
| 3 | `/compact` term pooled over 7 days; model-mix shares normalized |
