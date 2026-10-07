# Spend anomalies (UPG-07)

A runaway agent loop or broken prompt caching shows up only as a bigger bill. DevTelemetry flags days that cost far more than **that engineer's own normal**, and names the likely cause.

Code:
- `core/anomaly.py`: the detector;
- `analysis/anomaly_eval.py`: its evaluation;
- `GET /api/anomalies`, plus `anomalies` in `GET /api/engineer/{id}/details`;
- the dashboard "Spend anomalies" card and the engineer chart markers;
- a "Spend anomalies (last 7 days)" list in the manager digest.

## The detector

A day is compared with the same engineer's previous **28 days of the same type**: weekdays with weekdays, weekends with weekends. A quiet Saturday is never "unusual", and a busy Saturday is judged against other Saturdays and Sundays, not against Mondays. At least 8 baseline days are needed; 28 days hold exactly 8 weekend days. Without them, the day is not evaluated.

| Rule | Value | Why |
|---|---|---|
| Robust z = 0.6745 × (cost − median) / MAD | ≥ 3.5 | The usual cut-off for the modified z-score (Iglewicz & Hoaglin). The median and MAD barely move when one earlier incident sits in the baseline; a mean and standard deviation would be inflated by it and hide the next one. |
| cost − median | ≥ $5 | Unusual but small (a light user's $2 day doubling) is not worth anyone's attention. |
| MAD floor | $0.25 | A perfectly regular history (MAD = 0) must not flag every cent. |

**The driver** is the habit that explains most of the extra cost. It is found by re-pricing the day with the engineer's usual habit (`core.whatif.reprice_day`, the same re-pricing as the what-if savings):

| Driver | How it's measured |
|---|---|
| cache | Same day with the usual cache hit ratio. Answers "caching broke". |
| model_mix | Same day with the usual Opus share. |
| volume | Same habits at the usual token volume. Answers "a runaway agent loop". |

## Evaluation on injected incidents

**The setup:**
- **Teams:** 200 simulated teams of 10 engineers over 120 days, from the persona model in `data/seed.py`.
- **Incidents:** about one per engineer per month, at random positions (`data/seed.py: inject_incident`):
  - runaway loops: every token count ×3–6;
  - broken caching: cache hit ratio 5–15%.
- **Judging:** all detectors are judged on the same days, from day 28 on.

**The two baselines:**
- **Fixed $30:** one team-wide threshold. Anthropic's Claude Code cost docs put 90% of users below $30 per active day.
- **Mean + 3σ:** the textbook rule, given the same baseline windows and the same $5 floor, so the only difference is the statistic.

`python -m analysis.anomaly_eval` (output copied unchanged):

200 simulated teams of 10, 184000 engineer-days judged, 6170 injected incidents

| Detector | Precision | Recall | F1 | False alarms per engineer-month | Recall: runaway loop | Recall: broken cache | Recall: weekend incidents |
|---|---|---|---|---|---|---|---|
| Robust (median/MAD, own same-type days) | 66% | 72% | 0.69 | 0.37 | 91% | 51% | 57% |
| Fixed $30/day | 36% | 36% | 0.36 | 0.63 | 51% | 21% | 7% |
| Mean + 3 sd (same windows and $ floor) | 72% | 61% | 0.66 | 0.23 | 81% | 40% | 53% |

### What this shows

- **A fixed threshold is the wrong tool.** It catches 7% of weekend incidents (a light user's runaway loop on a Saturday stays under $30). It also raises the most false alarms (0.63 per engineer-month), because heavy users cross $30 on normal days.
- **The robust detector has the best F1** (0.69) at 0.37 false alarms per engineer-month, which meets the bar of ≤ 1. It catches 91% of runaway loops.
- **Mean + 3σ is more precise** (72% vs 66%) **but misses more** (61% vs 72% recall). Earlier incidents inflate its standard deviation, so later ones fall under the bar. Which you prefer depends on the cost of a missed incident versus an unneeded look. Here a missed runaway loop costs more than a glance at a dashboard.
- **Broken caching is the hard case** (51% recall). For an engineer whose hit ratio was already low, losing the cache adds only a few dollars, so it hides in normal variation. Watching the uncached-input tokens directly, rather than only the cost, would catch more. That is not built.

### On the demo data

`python data/seed.py` injects 3 incidents in the last 14 days (`--incidents 3`). The dashboard lists 5 anomalies:
- **The 3 injected days, all caught.** Two are runaway loops (driver: volume) and one is broken caching (driver: cache).
- **2 days of naturally heavy simulated usage.** A run with `--incidents 0` flags exactly those 2.

## Limits

- **Simulated incidents and noise.** Real incidents may be shaped differently (a slow leak over a week, not a one-day spike). The detector looks at single days only.
- **Cold start.** A new engineer has no baseline for 4 weeks on weekends, and about 2 weeks on weekdays.
- **The threshold is a trade-off.** The values (3.5, $5) were set before the evaluation, not tuned on it. A team that wants fewer alerts can raise either one.
