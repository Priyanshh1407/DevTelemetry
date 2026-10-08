# Did the coaching work? (UPG-05)

The product coaches the **bottom two engineers by that day's score** (the "critical" tier). This page explains how DevTelemetry estimates whether that coaching changes anything, and how the method was checked on simulated teams where the right answer is known.

Code:
- `core/impact.py`: the estimators;
- `core/coaching_log.py` and the `coaching_events` table: who was coached;
- `analysis/coaching_impact.py`: the validation;
- `GET /api/coaching-impact`: the dashboard card.

## Why the obvious number is wrong

The obvious metric is "the coached area's points in the week after coaching, minus the coaching day". It is biased upwards. Engineers are picked *because* they had a bad day, and a bad day is usually followed by a more normal one, whether or not anyone coached them. This is **regression to the mean**, and it makes coaching look like it works even when it does nothing.

## The method

For each coaching event (an engineer, the day they were selected, the area they were coached on), the outcome is that area's points **on single days**.

The `/compact` term is not pooled over 7 days here as the dashboard score pools it. With pooling, the "before" and "after" days would share data.

Two 7-day windows are compared:

| Window | Days | Why these days |
|---|---|---|
| Before | −13 … −7 | Skips days −6 … −1. Those days are pooled into the selection day's `/compact` score, so they were selected on as well. |
| After | +1 … +7 | The first week after the coaching. |

Both windows contain each weekday exactly once, so weekday/weekend differences cancel.

| Estimate | Formula | Problem it has or fixes |
|---|---|---|
| Naive | mean(after) − selection day | Biased by regression to the mean. Shown only with that label. |
| Before/after | mean(after) − mean(before) | No selection bias, but anything that changed for the whole team (a tooling update, a deadline) is credited to the coaching. |
| **Difference-in-differences** | before/after − the same change for engineers **not** coached around that day | Removes team-wide changes. Assumes coached and uncoached engineers would have moved in parallel without the coaching. |

Some events are left out, with the reason shown:
- **Overlapping coaching:** another coaching of the same engineer would land in either window.
- **Insufficient data:** fewer than 5 days in a window.
- **No comparison group:** no engineer was uncoached in that period.

The 95% interval is a **cluster bootstrap**. Events on the same day share their comparison group, so whole coaching days are resampled (1,000 times, fixed seed). With only one coaching day, no interval is given.

## Validation on simulated teams

Real coaching has no answer key, so the method was checked where the answer is known.

**The setup:**
- **Teams:** 200 simulated teams of 10 engineers over 168 days, from the persona model in `data/seed.py`.
- **Coaching:** every 14 days the critical engineers are coached on their weakest area, exactly as the product does it.
- **Effect:** with probability 0.7, a coached engineer changes that habit, by:
  - cache hit +8 points;
  - 15% of usage moved from Opus to Sonnet;
  - `/compact` in 25% more sessions.
- **Background drift:** the whole team's cache hit ratio drifts up by 0.002 a day.

Every engineer-day draws its noise from its own seeded random stream. That makes it possible to regenerate each coached day with the engineer's habit from *before* the coaching. The difference is the exact effect of that coaching on that day: a coupled counterfactual, and the "truth" below.

`python -m analysis.coaching_impact` (output copied unchanged):

### True effect: none (200 simulated teams of 10, 168 days each)

Mean true effect: +0.00 points in the coached area. Events per team: 22.0 estimated, 2.0 excluded.

| Method | Mean estimate | Bias | 95% CI covers the truth | Teams where the CI says "it worked" |
|---|---|---|---|---|
| Naive (after - coaching day) | +0.82 | +0.82 | 82% | 18% |
| Before/after (clean baseline) | +0.04 | +0.04 | 98% | 0% |
| Difference-in-differences | +0.02 | +0.02 | 98% | 2% |

Cache-coached events only (102 of 4400; the team-wide caching drift acts here): bias per event naive +1.91, before/after +1.06, difference-in-differences +0.11.

### True effect: moderate (200 simulated teams of 10, 168 days each)

Mean true effect: +4.13 points in the coached area. Events per team: 22.0 estimated, 2.0 excluded.

| Method | Mean estimate | Bias | 95% CI covers the truth | Teams where the CI says "it worked" |
|---|---|---|---|---|
| Naive (after - coaching day) | +5.74 | +1.62 | 86% | 84% |
| Before/after (clean baseline) | +4.19 | +0.06 | 98% | 98% |
| Difference-in-differences | +4.13 | +0.01 | 98% | 98% |

Cache-coached events only (261 of 4400; the team-wide caching drift acts here): bias per event naive +1.91, before/after +1.19, difference-in-differences +0.30.

### What this shows

- **Naive is fooled by the selection.** With coaching that does nothing, it still reports +0.82 points and declares success in 18% of teams. With a real effect it overstates it by 39% (+5.74 vs +4.13).
- **Difference-in-differences recovers the truth.** It is within 0.02 points under no effect and within 0.01 under the moderate one (0.2% of the effect). Its interval covers the truth in 98% of teams and claims an effect in only 2% of the no-effect teams.
- **The comparison group matters when the whole team moves.** On cache-coached events, where the drift acts, before/after credits the coaching with +1.06 points of team-wide drift. Difference-in-differences removes almost all of it (+0.11).
- **The naive bias is moderate here (+0.8 points)** because simulated day-to-day noise is small next to the differences between engineers' habits. Noisier real data would make it larger.

### On the demo data

`python data/seed.py` now generates 120 days with simulated coaching at the moderate effect. On that data the dashboard card shows **+3.0 points (95% CI +1.6 to +4.5)** from 16 coaching events over 8 rounds. Naive shows +2.6 with an interval that includes zero.

That is one team, so the numbers are noisier than the 200-team averages above.

## Limits

- **Parallel trends is an assumption, not a fact.** If the bottom two would have improved faster than everyone else anyway (for example, new joiners finding their feet), difference-in-differences credits that to the coaching. A random holdout is the gold standard: coach a random half of the critical engineers and compare. It is not done here because withholding coaching from people who need it is a product and ethics decision.
- **The comparison group is not randomized.** Uncoached engineers are, by construction, the better scorers.
- **Effects are measured one week out.** Whether habits last longer would need a longer "after" window.
- **The validation proves the method, not the coaching.** The simulated effect sizes are assumptions, not measurements of real coaching. With real data, the same code reports whatever effect is there.
- **Weekly dispatch overlaps.** With the default weekly schedule, an engineer who stays in the bottom two is coached every 7 days, and those events overlap. They are excluded and counted under "excluded" on the card. The simulation coaches every 14 days.
