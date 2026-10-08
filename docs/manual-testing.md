# DevTelemetry — complete test guide

This guide lets someone who has never seen the project install it, then check **every feature** and **how it behaves when things go wrong**: AI provider down, bad input, attackers, a lost database, duplicate requests, a server restart. Each test gives the command, the expected outcome, and why it matters.

- **Shell:** every command is for **Git Bash**. On macOS/Linux the only change is `source venv/bin/activate` instead of `source venv/Scripts/activate`.
- **Time:** about 15 minutes for setup and the automated checks (sections 1–2); 60–90 minutes for everything.
- **Safe by design:** the tests use a separate database (`data/test.db`) and a test admin token, and email and Slack are blanked, so nothing real is touched or sent.
- **Expected values:** the demo data ends on the day you generate it, so exact numbers change a little from day to day. Values below come from a run on **2026-10-07**; on another day expect similar values and the same behaviour.
- **Read this file rendered** (on GitHub, or in VS Code with Ctrl+Shift+V) and copy commands from there. Inside tables, a pipe is written `\|` in the raw Markdown; the rendered view shows the plain `|` that bash needs.
- **Mark each test** ✅ or ❌ in the checklist at the end. If something fails, note the test ID (e.g. `R4`) and what you saw.

---

## 1. Setup

### 1.1 Prerequisites

```bash
git --version          # any recent version
python --version       # 3.13 or newer
node --version         # 22 or newer
docker --version       # optional, only for section 7
```

### 1.2 Get the code and install

```bash
git clone https://github.com/Priyanshh1407/DevTelemetry.git
cd DevTelemetry
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
(cd frontend && npm ci)
```
**Expected:** every install finishes without errors. `.env` now exists with every secret blank.

### 1.3 The test environment (paste into EVERY terminal you open)

```bash
cd DevTelemetry                      # wherever you cloned it
source venv/Scripts/activate
export DB_PATH="$PWD/data/test.db"   # a throwaway database (ignored by git)
export ADMIN_TOKEN=test-admin        # the admin password for this test run
export EMAIL_SENDER= EMAIL_PASSWORD= EMAIL_RECIPIENT= SLACK_WEBHOOK_URL=   # never send real messages
export GEMINI_API_KEY=               # start without AI (sections marked [AI] turn it on)
B=http://localhost:8000
ADMIN="X-Admin-Token: test-admin"
JSON="Content-Type: application/json"
```
**Why:** settings in the shell win over `.env` (python-dotenv never overrides them). So this run uses its own database and token and can't send email or Slack, even if `.env` holds real credentials.

### 1.4 Generate the demo data and start the app

```bash
python data/seed.py --reset
```
**Expected:**
- `Ingested 1200 new and 0 refreshed engineer-days.` (10 engineers × 120 days)
- `Simulated 16 coaching events (true effect: moderate).`
- `Injected 3 incident days in the last 14 days.`

Open **terminal A** (with the 1.3 block) and start the API:
```bash
uvicorn api.main:app --reload
```
**Expected:** `Uvicorn running on http://127.0.0.1:8000`.

Open **terminal B** (with the 1.3 block) and start the dashboard:
```bash
cd frontend && npm run dev
```
**Expected:** `Local: http://localhost:5173/`.

Use **terminal C** (with the 1.3 block) for every `curl` command below.

---

## 2. Automated checks (the whole system in about 3 minutes)

Run these in terminal C. Together they cover over 400 backend tests, 46 frontend tests, the recorded AI evals and the two validation studies.

| ID | Command | Expected | What it proves |
|---|---|---|---|
| A1 | `pytest` | all pass (435 at the time of writing) | Backend behaviour, including every failure path in sections 5–6. Network access is blocked and the real database is guarded, so tests can't send anything or touch real data. |
| A2 | `pytest -q --cov=core --cov=api --cov=ai --cov=notifications --cov=data --cov=main --cov-fail-under=85` | `Required test coverage of 85% reached. Total coverage: 97.6%` (about) | The same coverage gate CI enforces |
| A3 | `ruff check .` | `All checks passed!` | Python lint (bugbear rules, no stray prints) |
| A4 | `(cd frontend && npm test && npm run lint && npm run build)` | `46 passed`, no lint output, `✓ built` | Dashboard components, error states, production build |
| A5 | `python -m evals.run --pipeline v3` | Valid 100%, first action targets the weakest area 100%, grounded 100% of 552 numbers, quoting a computed saving 96.7%. One log line "Guide output invalid … asking for a repair" is expected (profile p10 needed its one repair). | AI coaching quality, re-scored from recorded replies (no API calls) |
| A6 | `python -m evals.team_run --pipeline team-v2` then `--pipeline team-v1` | team-v2: targets the team's biggest gap **100%**; team-v1 (old memo): **0%**. 0 invented commands in both. | The grounded team memo beats the old one |
| A7 | `python -m analysis.coaching_impact` (~1 min) | Same tables as [impact.md](impact.md): naive +0.82 vs DiD +0.02 with no true effect; DiD +4.13 vs a true +4.13 | The coaching-impact method is right where the answer is known |
| A8 | `python -m analysis.anomaly_eval` (~1 min) | Same table as [anomalies.md](anomalies.md): robust F1 0.69 vs fixed threshold 0.36 | The anomaly detector beats the obvious alternatives |
| A9 | `git status` | `nothing to commit, working tree clean` | Re-scoring never rewrites published results; test files are git-ignored |

---

## 3. Core features

### 3.1 Health and API docs

| ID | Do | Expected |
|---|---|---|
| F1 | `curl -s $B/health` | `{"status":"ok","database":"ok","scoring_version":"3","latest_data_date":"<today>","ai_configured":false}` |
| F2 | Open http://localhost:8000/docs | Interactive API docs listing every endpoint |

### 3.2 Dashboard (http://localhost:5173)

| ID | Do | Expected |
|---|---|---|
| F3 | Open the dashboard | **Team Size 10**; **Avg Efficiency** around 55–60 /100 with a bar; **Total Daily Spend** with a red/green "% vs previous day" |
| F4 | Look at **Trend Analysis** | A 30-day chart: average score (solid line) and total cost (dashed). Hovering shows both values for a day. |
| F5 | Look at **Team Leaderboard** | 10 rows sorted by score. The top 3 have gold/silver/bronze rank badges. Each score has a 7-day change (green up, red down, grey flat) and a small activity bar chart. |
| F6 | Click **EXPORT CSV** | Downloads `devtelemetry-leaderboard.csv` with the header `rank,user_id,name,efficiency_score,estimated_cost_usd` and 10 rows matching the table |
| F7 | Click any leaderboard row | Opens that engineer's page |

### 3.3 Engineer page

| ID | Do | Expected |
|---|---|---|
| F8 | Header card | Name and initials, `Rank #N`, a severity badge (top 5 = LOW, bottom 2 = CRITICAL, others MODERATE), latest score and latest day's cost |
| F9 | Score breakdown | Three bars, **Prompt caching x/40**, **Model choice x/30** and **Context management (/compact, 7 days) x/30**, adding up to the latest score. The weakest is highlighted with "Biggest opportunity: …". |
| F10 | Rest of the page | 30-day average cards (cache hit, sessions, commits, /compact rate); 30-day score trend; latest model mix pie; daily spend chart; three plain-language insights |

### 3.4 Coaching runbook

| ID | Do | Expected |
|---|---|---|
| F11 | On an engineer page click **VIEW PERSONAL OPTIMIZATION RUNBOOK** | Severity badge, "Your biggest opportunity is …", score / biggest opportunity / cost cards, and a guide whose **first action is about the weakest area**. Without AI there's a note: "Rule-based guide built from your sub-scores, because the AI provider is unavailable." |
| F12 | Tick an action's checkbox | The counter changes, e.g. `1/3 done` (per browser tab only, by design) |
| F13 | `curl -s $B/api/guide/<user_id> \| python -m json.tool` | `guide` (title/desc list), `coaching` (headline + actions with `focus`), `source`, `cached` |

### 3.5 Alert schedule and sending alerts (admin)

| ID | Do | Expected |
|---|---|---|
| F14 | At the bottom of the dashboard choose **Daily**, a time, then **SAVE SYNC** and enter `test-admin` when asked | Toast "Alert schedule saved successfully." The timezone label shows your browser's timezone. Reload: the values stay. |
| F15 | Close the tab, open the dashboard again, **SAVE SYNC**, and enter `wrong` | Toast "Schedule not saved: Missing or invalid admin token." (the wrong token is not kept) |
| F16 | Click **TEST ALERTS NOW** (token `test-admin`) | Toast "Alerts not fully sent: Nothing was sent: email and Slack are not configured on the server." The run is real and honest: nothing is configured, so nothing claims success. |
| F17 | `curl -s $B/api/dispatch-runs/1 \| python -m json.tool` | `status: "skipped"`, with per-channel counts (`developer_emails.skipped: 10`, `manager_digest: "skipped"`, `slack: "skipped"`) and a message |

### 3.6 Ingestion API (how real usage gets in)

```bash
TODAY=$(date +%F)
REC="{\"user_id\":\"new-dev\",\"date\":\"$TODAY\",\"name\":\"New Dev\",\"email\":\"new@example.com\",\"input_tokens\":400000,\"output_tokens\":30000,\"cache_read_tokens\":2500000,\"cache_write_tokens\":150000,\"opus_pct\":0.2,\"sonnet_pct\":0.6,\"haiku_pct\":0.2,\"session_count\":4,\"compact_uses\":2}"
```

| ID | Do | Expected |
|---|---|---|
| F18 | `curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d "{\"records\":[$REC]}"` | `{"inserted":1,"updated":0,"rejected":[]}`; reload the dashboard: **New Dev** is on the leaderboard (team of 11), with cost and score computed by the server |
| F19 | Send the same command again | `{"inserted":0,"updated":1,"rejected":[]}`: re-sending updates, never duplicates |

### 3.7 Console agent and data generator

| ID | Do | Expected |
|---|---|---|
| F20 | `python main.py` | Prints the leaderboard, a **TEAM-WIDE OPTIMIZATION REPORT** (team memo) and guides for the bottom 5, each marked `(fallback guide: unavailable)` without AI |
| F21 | `python data/seed.py` (no `--reset`) | `Ingested 0 new and 1200 refreshed engineer-days.` (idempotent: same engineers, no duplicates; New Dev stays) |
| F22 | `python data/seed.py --if-empty` | `Database already has usage data; skipping seed.` (what containers run at start) |

---

## 4. Measured features (Phase 8)

### 4.1 Did the coaching work?

| ID | Do | Expected (2026-10-07) |
|---|---|---|
| P1 | Dashboard → **Coaching impact** card | **+3.0** points, `95% CI +1.6 to +4.5`, green "Improvement detected", "From 16 coaching events". Below: `+2.6 naive before/after (biased by regression to the mean)…` |
| P2 | `curl -s $B/api/coaching-impact \| python -m json.tool` | `n_events: 16`, `window: {pre: [-13, -7], post: [1, 7]}`; `naive`, `pre_post`, `did` each with an estimate and CI; every event with name, date, area and a status |
| P3 | Open `http://localhost:5173/engineer/<user_id>` for a `user_id` from P2 | Green dashed lines on the score chart and "Coached MM-DD on …" under it |
| P4 | **Experiment:** `python data/seed.py --reset --coaching-effect none`, then refresh | About **+0.2**, CI around −1.8 to +2.2, grey "**No clear effect yet**". The method doesn't invent an effect. Then restore with `python data/seed.py --reset`. |

### 4.2 What-if savings

| ID | Do | Expected |
|---|---|---|
| P5 | Engineer page → **What-if savings** | Sliders starting at the team's top quartile ("Defaults are the team's top quartile (…% cache hit, …% Opus)"), savings for Caching / Model choice / Both, and "Now $X per 30 days" |
| P6 | Drag **Cache hit target** up | After about 0.3 s the Caching and Both savings rise (one engineer: +10 points took it from $81.24 to $144.19) |
| P7 | Drag it below "(now …)"; set **Opus share at most** to 100% | Those savings become **$0.00**. A target only ever improves a habit, so a saving is never negative. |
| P8 | Open the engineer's runbook | The rule-based guide quotes the same savings: "…would save $X per 30 days". [AI] With a key, the AI guide quotes them too. |

### 4.3 Spend anomalies

| ID | Do | Expected (2026-10-07) |
|---|---|---|
| P9 | Dashboard → **Spend anomalies** | 5 rows: "$X (usually $Y) · likely …". Three are injected incidents (2 × "more tokens (runaway agent loop)", 1 × "caching broke"); two are naturally heavy days. |
| P10 | Click a name | Engineer page with pink dotted lines and "Unusual spend MM-DD: $X, likely …" |
| P11 | **Experiment:** `python data/seed.py --reset --incidents 0`, then refresh | **2** rows (only the natural ones), so the other 3 were the injected incidents. Restore with `python data/seed.py --reset`. |

### 4.4 Grounded team memo

| ID | Do | Expected |
|---|---|---|
| P12 | `python main.py`, section **TEAM-WIDE OPTIMIZATION REPORT** | "The team of 10 averaged … The biggest team-wide gap is …", then "Focus on …" lines. Every number is a real team fact; only real Claude Code commands are mentioned (from `/compact`, `/clear`, `/model`). |
| P13 | [AI] `unset GEMINI_API_KEY` (so the key in `.env` is used), restart terminal A, run `python main.py` again | A model-written memo in the same shape. The first focus is the biggest gap, and only `/compact /clear /context /model /usage` appear. Afterwards run `export GEMINI_API_KEY=` and restart terminal A. |

---

## 5. Resilience: what happens when things go wrong

Each test causes one failure on purpose. **The system must keep working, tell the truth about what happened, and never corrupt data.**

### 5.1 AI provider problems

| ID | Scenario | How | Expected | Why it matters |
|---|---|---|---|---|
| R1 | No AI key | (the default in 1.3) | Runbooks, `main.py` and the team memo all work with rule-based content built from the real numbers; `/health` says `ai_configured: false` | The product works without a paid dependency |
| R2 | AI provider rejects the request | In terminal A: `export GEMINI_API_KEY=invalid-key-for-testing` and restart the API. In terminal C: `U=$(curl -s $B/api/leaderboard \| python -c "import json,sys;print(json.load(sys.stdin)[-1]['user_id'])")`, then `curl -s $B/api/runbook-tasks/critical/$U \| python -m json.tool` | `"source": "unavailable"`, `"cached": false`, and real rule-based tasks. Opening that runbook in the browser shows the same guide with "…because the AI provider is unavailable." | An outage degrades to useful content, never a blank page or a 500 |
| R3 | The failure is not cached | Run the same `curl` again, then `curl -s "$B/api/ai-stats" \| python -m json.tool` | Again `"cached": false`. `by_outcome` counts only `unavailable` (no `cache_hit`) and `fallback_rate` is `1.0`: a fallback is never stored and served as if it were an AI answer, so when the provider recovers, real guides come back immediately. (The browser in dev mode sends each request twice, so use `curl` for exact counts.) Afterwards: `export GEMINI_API_KEY=` in terminal A and restart. | A past bug: one outage used to poison every runbook until a restart |
| R4 | Rate limit / overload → backup model | `pytest tests/test_model_fallback.py -v` | All 9 tests pass, including `test_rate_limit_or_overload_retries_once_on_the_fallback_model` and `test_after_a_failure_the_main_model_is_skipped_for_a_cooldown` | Free-tier quotas are per model, so the backup model keeps AI available |
| R5 | The model returns broken output | `pytest tests/test_coaching.py -v -k "invalid or repair"` | Invalid JSON gets exactly **one** repair attempt, then the rule-based guide (bounded cost) | LLMs are unreliable; the product isn't |
| R6 | The memo invents a Claude Code feature | `pytest tests/test_team_memo.py -v -k invented` | A reply with `/optimize-tokens` or `.claudedir` is repaired, then replaced, and never shown | Wrong advice to a manager is worse than none |

### 5.2 Bad or hostile input (every one must be rejected cleanly, never a crash)

| ID | Command (terminal C) | Expected |
|---|---|---|
| R7 | `curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/settings -H "$ADMIN" -H "$JSON" -d '{"frequency":"Weekly","day":"Friday","time":"25:99"}'` | `422` (impossible time) |
| R8 | Same with `"time":"17:00","timezone":"Mars/Base"` | `422` (unknown timezone) |
| R9 | Same with `"frequency":"Hourly","time":"17:00"` | `422` (unsupported schedule) |
| R10 | `curl -s -o /dev/null -w "%{http_code}\n" $B/api/runbook-tasks/urgent/new-dev` | `422` (unknown severity) |
| R11 | `curl -s -o /dev/null -w "%{http_code}\n" "$B/api/engineer/new-dev/what-if?cache_hit=0.99"` and `?opus_pct=abc` | `422` and `422` |
| R12 | `curl -s -o /dev/null -w "%{http_code}\n" "$B/api/anomalies?days=0"`, `"$B/api/coaching-impact?days=400"`, `"$B/api/ai-stats?purpose=hack"` | `422` each |
| R13 | `curl -s -o /dev/null -w "%{http_code}\n" $B/api/engineer/nobody/details` and `$B/api/dispatch-runs/99999` | `404` each |
| R14 | Ingest a record with negative tokens: `curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d "{\"records\":[${REC/400000/-5}]}"` | `rejected` with `input_tokens: Input should be greater than or equal to 0`; nothing written |
| R15 | Five more kinds of bad record in one batch: `python -c "import json,sys; r=json.loads(sys.argv[1]); print(json.dumps({'records':[dict(r,opus_pct=1.0), dict(r,compact_uses=9), dict(r,date='2030-01-01'), dict(r,cache_reads=1), dict(r,estimated_cost_usd=1)]}))" "$REC" \| curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" --data-binary @- \| python -m json.tool` | `inserted: 0` and 5 entries in `rejected`, each with its own reason: "must sum to 1", "cannot exceed session_count", "date is in the future", "Extra inputs are not permitted", "computed by the server" |
| R16 | Mixed batch, one good and one bad: `python -c "import json,sys; r=json.loads(sys.argv[1]); print(json.dumps({'records':[dict(r,user_id='good-dev'), dict(r,user_id='bad-dev',input_tokens=-5)]}))" "$REC" \| curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" --data-binary @-` | `"inserted":1` and `bad-dev` listed by index in `rejected`: one bad row doesn't sink the batch |
| R17 | `curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d '{"records": [oops'` | `422` (malformed JSON) |
| R18 | `curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d '{"records":[]}'` | `422` (empty batch) |
| R19 | 1,001 records: `python -c "import json,sys; r=json.loads(sys.argv[1]); print(json.dumps({'records':[dict(r,user_id=f'u{i}') for i in range(1001)]}))" "$REC" > big.json && curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" --data-binary @big.json; rm big.json` | `422` (batch limit 1,000) |

### 5.3 Duplicates, races and restarts

| ID | Scenario | How | Expected |
|---|---|---|---|
| R20 | A scheduled slot is sent once | `NOW=$(date -u +%H:%M)`; `curl -s -X POST $B/api/settings -H "$ADMIN" -H "$JSON" -d "{\"frequency\":\"Daily\",\"day\":\"Monday\",\"time\":\"$NOW\",\"timezone\":\"UTC\"}"`; then run `curl -s -X POST $B/api/scheduled-tick -H "$ADMIN"` **twice** | First: `"status":"started"` with a slot. Second: `"status":"already_sent"` for the same slot. The cron may call any number of times, but each slot is sent once. |
| R21 | Nothing scheduled now | Set the time to an hour from now and tick | `{"status":"not_due"}` |
| R22 | No data, no dispatch | (After R26's empty restart) `curl -s -X POST $B/api/trigger-alerts -H "$ADMIN"` | `409` "No usage data to report yet." |
| R23 | Two alert dispatches at once | `pytest tests/test_dispatch.py -v` | `test_concurrent_starts_from_many_threads_admit_exactly_one` passes: the **database** enforces a single running dispatch, across processes |
| R24 | The server dies mid-dispatch | (same test file) | `test_stale_running_row_is_abandoned_instead_of_blocking_forever`: a run left "running" by a crash is marked `abandoned`, so it never blocks future alerts |
| R25 | Repeat sends within 5 minutes | `pytest tests/test_dispatch.py -v -k cooldown` | A run that delivered something starts a 5-minute cooldown (`429` with `Retry-After`). A run that delivered nothing ("skipped", as in F16) doesn't, so you can retry right away. To see the 429 live you need real email settings. |
| R26 | **The database file disappears while the API runs** | Terminal C: `rm "$DB_PATH"`; then `curl -s $B/health -w " [%{http_code}]\n"` and `curl -s -o /dev/null -w "%{http_code}\n" $B/api/leaderboard` | `/health`: `{"status":"error","database":"unreachable"} [503]`. Leaderboard: `500` with a generic body (no paths or SQL leaked). On Render, the 503 makes the platform restart the service. |
| R27 | Restart on the missing database | Restart terminal A (Ctrl+C, then `uvicorn api.main:app --reload`) | `/health` → `ok` with `latest_data_date: null`. Every page and endpoint works with an empty team: leaderboard `[]`, dashboard "Team Size 0", the coaching card "No coaching with enough data…", anomalies "No unusual spend…", no errors. Then `python data/seed.py --reset` to restore. |
| R28 | A brand-new engineer isn't judged without history | `curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d "{\"records\":[${REC/new-dev/fresh}]}"` then `curl -s "$B/api/anomalies?days=90" \| grep -c fresh` | `0`: with no history (fewer than 8 comparable days) a day is **not evaluated** rather than wrongly flagged |
| R29 | Old databases upgrade themselves | `pytest tests/test_migrations.py -v` | Old rows are converted and rescored once; a second start changes nothing |
| R30 | A slow AI call doesn't freeze the app | `pytest tests/test_concurrency.py -v` | Passes: while a guide takes seconds to generate, the leaderboard still answers immediately (handlers run in a thread pool) |

### 5.4 The dashboard under failure

| ID | Scenario | How | Expected |
|---|---|---|---|
| R31 | API completely down | Stop terminal A (Ctrl+C) and reload the dashboard | "Couldn't load team telemetry." with the error and a **RETRY** button. Start the API again and click **RETRY**: the dashboard loads. |
| R32 | One endpoint failing | In Edge or Chrome: DevTools (F12) → Network → right-click a request to `/api/anomalies` → **Block request URL**, then reload | Only the Spend anomalies card shows "Couldn't load anomalies: …". Everything else works. (Unblock afterwards.) |
| R33 | Unknown engineer | Open http://localhost:5173/engineer/nobody | "Error Loading Data / Engineer not found" with a link back |
| R34 | Unknown engineer's runbook | Open http://localhost:5173/runbook/critical/nobody | "Couldn't load this runbook. No usage data for this engineer." |
| R35 | Honest delivery reporting | `pytest tests/test_alerts.py -v` | `test_all_emails_failing_is_not_reported_as_success` and `test_partial_failure_is_reported` pass (a past bug showed "All alerts dispatched!" even when everything failed) |

---

## 6. Security

| ID | Check | How | Expected |
|---|---|---|---|
| S1 | Admin actions need the token | `curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/api/trigger-alerts` and again with `-H "X-Admin-Token: wrong"` | `401` and `401` |
| S2 | Fail closed | Terminal A: `export ADMIN_TOKEN=`, restart, then `curl -s -X POST $B/api/trigger-alerts -H "X-Admin-Token: anything"` | `503` "Admin actions are disabled: ADMIN_TOKEN is not configured." (no token = disabled, never open). Restore with `export ADMIN_TOKEN=test-admin` and restart. |
| S3 | Only the dashboard may call the API from a browser | `curl -s -D - -o /dev/null -H "Origin: https://evil.example" $B/api/leaderboard \| grep -i access-control` then the same with `Origin: http://localhost:5173` | First: no output (no permission). Second: `access-control-allow-origin: http://localhost:5173`. |
| S4 | A foreign site can't trigger admin actions | `curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS $B/api/trigger-alerts -H "Origin: https://evil.example" -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: X-Admin-Token"` | `400` (preflight refused) |
| S5 | SQL injection | `curl -s -o /dev/null -w "%{http_code}\n" "$B/api/engineer/x'%20OR%20'1'='1/details"` and `"$B/api/engineer/1%3BDROP%20TABLE%20engineers/what-if"`, then count the leaderboard | `404`, `404`, and the team is intact (every query uses parameters) |
| S6 | Script injection (XSS) | Ingest a name with HTML: `curl -s -X POST $B/api/ingest -H "$ADMIN" -H "$JSON" -d "{\"records\":[${REC/New Dev/<img src=x onerror=alert(1)>}]}"`, then reload the dashboard | The name shows **as text**, `<img src=x onerror=alert(1)>`, and no popup appears. (Emails escape it too: `pytest tests/test_notifications.py -k escaped`.) |
| S7 | IDs are allow-listed | Ingest with `"user_id":"<b>"` | Rejected: `String should match pattern '^[A-Za-z0-9._:@-]+$'` |
| S8 | No secrets in responses or errors | `curl -s $B/health` | Only `ai_configured: true/false`, never the key. R26 showed errors return a generic body; details stay in the server log. |
| S9 | Personal data never goes to the AI | `pytest tests/test_api.py -v -k no_name_or_email` | Passes for every AI path: prompts carry metrics only, never names or emails |
| S10 | Tests can't leak | `pytest tests/test_safety.py -v` | Outbound network blocked, mocked AI client, temp database |
| S11 | Python dependencies | `python -m venv ../audit-venv && ../audit-venv/Scripts/pip install -q pip-audit && ../audit-venv/Scripts/pip-audit -r requirements.txt` (a separate venv next to the project; delete it afterwards) | `No known vulnerabilities found` |
| S12 | JavaScript dependencies | `(cd frontend && npm audit)` | `found 0 vulnerabilities` |
| S13 | No secrets in the repository | `git grep -I -n -E 'AIza[0-9A-Za-z_-]{35}\|sk-[A-Za-z0-9_-]{20,}\|ghp_[A-Za-z0-9]{36}\|xox[baprs]-\|BEGIN [A-Z ]*PRIVATE KEY'` | No output |
| S14 | Private files can't be committed | `git check-ignore -v .env .env.local data/test.db data/usage.db` and `git ls-files \| grep -i "\.env\|\.db"` | Each file matched by a `.gitignore` rule; only `.env.example` is tracked |
| S15 | The container doesn't run as root | (needs section 7) `docker compose exec backend id -un` | `appuser` |

**Known limits (by design, documented):**
- **One shared admin token**, not user accounts; it's kept in the browser's sessionStorage until the tab closes.
- **Read endpoints are public**, which is fine for simulated demo data.
- **No per-IP rate limiting**, apart from the dispatch cooldown and the batch size limit.

---

## 7. Deployment and availability (Docker)

Stop terminals A and B first (they use the same ports).

| ID | Do | Expected |
|---|---|---|
| D1 | `docker compose up --build -d` | Both containers start. `curl -s localhost:8000/health` → `ok`. http://localhost:5173 shows the dashboard with a fresh team (the container seeds its own database). |
| D2 | Open `http://localhost:5173/engineer/<user_id>` directly in a new tab and refresh | The page loads (nginx serves the app for every route, so links in alert emails work) |
| D3 | `docker compose exec backend id -un` | `appuser` (not root) |
| D4 | `docker compose restart backend`, then `docker compose logs backend \| tail -5` | `Database already has usage data; skipping seed.` (data survives restarts on its named volume) |
| D5 | `docker compose down -v` | Containers and volume removed |

**On Render (the live demo):**
- `render.yaml` sets `healthCheckPath: /health`, so a failing database (R26) gets the service restarted automatically.
- The free tier sleeps when idle, so the first request takes 30–60 s.

**On GitHub (repository owner):**
- Every push and PR runs CI (A1–A4 on Python 3.13 and 3.14).
- The Actions tab shows the result.
- How to switch workflows off is in the README.

---

## 8. Clean up

```bash
rm -f data/test.db
docker compose down -v 2>/dev/null
```
Your own `data/usage.db` and `.env` were never touched.

---

## 9. Checklist

| Area | Tests | ✅ / ❌ | Notes |
|---|---|---|---|
| Setup | 1.1–1.4 | | |
| Automated checks | A1–A9 | | |
| Core features | F1–F22 | | |
| Coaching impact | P1–P4 | | |
| What-if savings | P5–P8 | | |
| Spend anomalies | P9–P11 | | |
| Team memo | P12–P13 | | |
| AI failures | R1–R6 | | |
| Bad input | R7–R19 | | |
| Duplicates, races, restarts | R20–R30 | | |
| Dashboard under failure | R31–R35 | | |
| Security | S1–S15 | | |
| Docker / availability | D1–D5 | | |

If every row is ✅, the system works end to end, degrades safely when its dependencies fail, rejects bad and hostile input, and keeps no secrets in the code.
