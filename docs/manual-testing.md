# Manual test guide

How to check every upgraded feature by hand, with the expected outcome of each step. The automated suite (section 1) covers the same behaviour; this guide is for seeing it work.

**Before you start:**
- **The setup resets your local demo database** (`data/usage.db`). It only holds simulated data.
- **The demo data ends on the day you seed it**, so exact numbers change from day to day. The numbers below come from a run on **2026-10-07**; on another day expect similar values and the same behaviour.
- **With a `GEMINI_API_KEY` in `.env`,** opening a runbook or running `main.py` makes real Gemini calls (about one per guide, within the free tier). Without a key, everything still works with rule-based guides and memos.

---

## 0. Setup

```bash
cd DevTelemetry
source venv/bin/activate          # Windows (Git Bash): source venv/Scripts/activate
python data/seed.py --reset
```
**Expected:**
- `Ingested 1200 new …`
- `Simulated 16 coaching events (true effect: moderate).`
- `Injected 3 incident days in the last 14 days.`

Then, in two terminals:
```bash
uvicorn api.main:app --reload                  # API on http://localhost:8000
cd frontend && npm run dev                     # dashboard on http://localhost:5173
```

## 1. Automated checks (about 3 minutes)

| Command | Expected |
|---|---|
| `pytest` | All tests pass (435 at the time of writing) |
| `ruff check .` | `All checks passed!` |
| `cd frontend && npm test && npm run lint && npm run build && cd ..` | All frontend tests pass (45), no lint errors, `✓ built` |
| `python -m evals.run --pipeline v3` | Valid 100%, targets the weakest area 100%, grounded 100% of 552 numbers, quoting a computed saving 96.7%. A log line "Guide output invalid … asking for a repair" is expected: it's profile p10, which needed a repair. |
| `python -m evals.team_run --pipeline team-v2` | Targets the team's biggest gap **100%**, 195 numbers, 0 invented commands |
| `python -m evals.team_run --pipeline team-v1` | Targets the team's biggest gap **0%** (the old free-text memo) |
| `python -m analysis.coaching_impact` (~1 min) | The same tables as [impact.md](impact.md): DiD +0.02 with no true effect and +4.13 with a true +4.13, 98% CI coverage |
| `python -m analysis.anomaly_eval` (~1 min) | The same table as [anomalies.md](anomalies.md): robust detector F1 0.69 |
| `git status` | Clean: replays never rewrite the published results |

## 2. Did the coaching work? (UPG-05)

| # | Do | Expected (2026-10-07) |
|---|---|---|
| 2.1 | Open http://localhost:5173 and find the **Coaching impact** card | **+3.0** points, `95% CI +1.6 to +4.5`, green "Improvement detected", "From 16 coaching events". Below: `+2.6 naive before/after (biased by regression to the mean)…` |
| 2.2 | `curl -s localhost:8000/api/coaching-impact \| python -m json.tool` | `n_events: 16`, `window: {pre: [-13, -7], post: [1, 7]}`, and `naive`, `pre_post`, `did` each with an estimate and CI. Each event has a name, date, area and a status (`included`, or why it was left out). |
| 2.3 | Copy a `user_id` from 2.2's events and open `http://localhost:5173/engineer/<user_id>` | Green dashed lines on the score chart, and "Coached MM-DD on …" under it |
| 2.4 | `curl -s -o /dev/null -w "%{http_code}" "localhost:8000/api/coaching-impact?days=0"` | `422` |
| 2.5 | **Experiment:** `python data/seed.py --reset --coaching-effect none`, then refresh | About **+0.2**, CI around −1.8 to +2.2, grey "**No clear effect yet**". The method doesn't invent an effect when the coaching did nothing. |

Run `python data/seed.py --reset` afterwards to restore the default data.

## 3. What-if savings (UPG-06)

| # | Do | Expected |
|---|---|---|
| 3.1 | On any engineer page, find the **What-if savings** panel | Two sliders starting at the team's top-quartile habits ("Defaults are the team's top quartile (…% cache hit, …% Opus)"), three savings boxes (Caching, Model choice, Both) and "Now $X per 30 days" |
| 3.2 | Drag **Cache hit target** up | After about 0.3 s the Caching and Both savings go up. On 2026-10-07, +10 points went from $81.24 to $144.19 for one engineer. |
| 3.3 | Drag the cache slider below the "(now …)" value | The Caching saving becomes **$0.00**. Targets only ever improve a habit. |
| 3.4 | Set **Opus share at most** to 100% | The Model choice saving becomes **$0.00** |
| 3.5 | `curl -s -o /dev/null -w "%{http_code}" "localhost:8000/api/engineer/<user_id>/what-if?cache_hit=0.99"` | `422` (the maximum is 0.97). `?opus_pct=2` → 422. `/api/engineer/nobody/what-if` → 404. |
| 3.6 | Click **VIEW PERSONAL OPTIMIZATION RUNBOOK** | **With a key:** an AI guide (no "Rule-based" note) whose cache or model action says "…would save $X per 30 days", matching the panel's numbers. **Without a key:** a "Rule-based guide…" note, with the same savings in the text. |
| 3.7 | Reload the same runbook | Instant: the stored guide is served, with no new model call |

## 4. Spend anomalies (UPG-07)

| # | Do | Expected (2026-10-07) |
|---|---|---|
| 4.1 | Dashboard → **Spend anomalies** card | 5 rows, each "$X (usually $Y) · likely …". Three are the injected incidents: two "more tokens (runaway agent loop)" and one "caching broke". The other two are naturally heavy days. |
| 4.2 | Click a name | That engineer's page, with pink dotted lines on the chart and "Unusual spend MM-DD: $X, likely …" under it |
| 4.3 | `curl -s localhost:8000/api/anomalies \| python -m json.tool` | `days: 14`, and every anomaly has `excess_usd ≥ 5`, `z ≥ 3.5` and a `driver` |
| 4.4 | `curl -s -o /dev/null -w "%{http_code}" "localhost:8000/api/anomalies?days=91"` | `422` |
| 4.5 | **Experiment:** `python data/seed.py --reset --incidents 0`, then refresh | **2** rows: only the natural heavy days remain, so the other three were the injected incidents |
| 4.6 | *(Optional: needs email settings and `ADMIN_TOKEN` in `.env`)* Click **TEST ALERTS NOW** | The manager email has a "Spend anomalies (last 7 days)" list |

Run `python data/seed.py --reset` afterwards to restore the default data.

## 5. Grounded team memo (UPG-08)

| # | Do | Expected |
|---|---|---|
| 5.1 | `python main.py` and look at **TEAM-WIDE OPTIMIZATION REPORT** | **With a key:** a short summary, then 1–2 lines starting "Focus on <area>:". The first is the team's biggest gap. Every number is a real team fact, and the only commands mentioned are `/compact`, `/clear`, `/context`, `/model` or `/usage`. |
| 5.2 | `GEMINI_API_KEY= python main.py` (key blanked for this run) | The rule-based memo: "The team of 10 averaged … The biggest team-wide gap is …", then "Focus on …" lines. No errors. |
| 5.3 | `pytest tests/test_team_memo.py -v` | Passes, including `test_an_invented_command_is_repaired` and `test_still_invented_after_repair_falls_back_to_the_rule_based_memo`. These show that a reply with `/optimize-tokens` or `.claudedir` never reaches the manager. |
| 5.4 | `curl -s "localhost:8000/api/ai-stats?purpose=team_report"` | `requests` goes up by one per `main.py` run |

## 6. Private files stay out of git

| Command | Expected |
|---|---|
| `git status --ignored` | `.env` and `data/usage.db` (and any local notes) are listed under "Ignored files"; nothing to commit |
| `git check-ignore -v .env .env.local data/usage.db` | Each line shows the `.gitignore` rule that ignores it |
| `git ls-files \| grep -i "\.env\|\.db"` | Only `.env.example` |

## 7. Docker (optional)

```bash
docker compose up --build        # http://localhost:5173 and http://localhost:8000/health
docker compose down -v           # when finished
```
**Expected:** the same dashboard as sections 2–4, built from scratch. Without a key in your shell, the runbook shows rule-based guides.
