# PROJECT AUDIT REPORT
Project: DevTelemetry | Type: Full-stack web app (FastAPI + SQLite + React/Vite) with an LLM feature (Gemini) and notification jobs (SMTP, Slack) | Audited: 2026-10-02 | Audit #: 1

Prior context read: `README.md`, `DEVTELEMETRY_INTERVIEW_REPORT.md` (untracked), `interview_study_guide.md`, `demo_commands.txt`. No previous `PROJECT_AUDIT_REPORT.md` / `UPGRADE_PLAN.md` / `FIX_LOG.md` existed, so this is the first audit.
Assumptions (not stated in repo): target roles = SDE **and** ML/AI Engineer; time budget = 3–4 weeks.

---

## 1. Executive Summary

- **Overall health:** A nicely presented prototype whose demo path works locally, but several core numbers are fabricated or random, the AI feature breaks on the deployed site, and the side-effecting endpoints are open to anyone.
- **Would this project survive a 45-minute deep-dive interview today? No.** The first “how is estimated cost calculated?” or “what happens if I POST to `/api/trigger-alerts`?” question exposes a P0. The test suite the commit history advertises has 3 of 10 backend tests failing, and the README describes features and files that don’t exist.
- **Findings:** P0 3 | P1 9 | P2 14 | P3 1 bundle (8 items) — TEST-02 added during Phase 0
- **Top 3 things to fix before any interview:**
  1. **SEC-01**: unauthenticated `POST /api/trigger-alerts` and `POST /api/settings` on a public deployment (sends real email/Slack and spends Gemini quota).
  2. **ML-01**: `estimated_cost_usd` is `random.uniform(5, 30)` and has nothing to do with tokens or model mix, yet the product pitch is cost reduction.
  3. **BUG-01**: Runbook page hardcodes `http://127.0.0.1:8000`, so the flagship AI feature can’t work on the live demo.

---

## 2. Baseline (commands actually run)

| Check | Command | Result |
|---|---|---|
| Backend tests (project venv) | `./venv/Scripts/python.exe -m pytest -q` | **Collection error ×2**: `ImportError: cannot import name 'genai' from 'google'`. The venv has the deprecated `google-generativeai 0.8.6`, not `google-genai` from `requirements.txt` |
| Backend tests (global Py 3.14 with google-genai 2.10) | `python -m pytest -q` | **7 passed, 3 failed**. All of `tests/test_generator.py` fails with `AttributeError: module 'ai.guide_generator' has no attribute 'model'` |
| Scorer tests only | `pytest tests/test_scorer.py` | 4 passed |
| Coverage | not configured | n/a |
| Lint (backend) | none configured (no ruff/flake8) | n/a |
| Frontend build | `npm run build` | ✓ built, warning: chunk > 500 kB |
| Frontend lint | `npm run lint` | **16 errors**, all `no-unused-vars` |
| Frontend tests | `npx vitest run` | 3 passed (1 file, Navbar only) |
| Frontend dep audit | `npm audit --omit=dev` | **5 vulns (4 high, 1 moderate)**: vite, react-router, postcss, nanoid; `npm audit fix` available |
| Python dep audit | `pip-audit` not installed | skipped (didn’t install it without asking) |
| App startup (no API key) | import `api.main` with `GEMINI_API_KEY` unset | **Crash**: `ValueError: No API key was provided` at import time (ERR-01) |
| Fresh-clone agent run | `git archive HEAD` → scratch dir → `python main.py` | **Crash**: `FileNotFoundError: engineers_data.json` (BUG-04) |
| Secret exposure | `git ls-files \| grep -Ei '\.env…'` and `git grep` for key patterns + `git log -S AIza` | Only `.env.example` is tracked. `.env` is git-ignored. No key patterns found in source or history ✓ |
| Commit history | `git log --oneline` | 7 commits total, including “Final changes done” and “Final production release” |

All reproductions ran on a throwaway copy in the scratchpad. The developer’s `data/usage.db` was opened **read-only** only. No emails, Slack posts, or paid API calls were made (one Gemini call went out with a dummy key and was rejected with 400).

Not run: the live Render deployment (I didn’t want to trigger side effects on a public URL), and `docker compose up` (Docker not exercised).

---

## 3. What Is Already Good

- **All SQL is parameterized** (`api/routes.py`, `data/seed.py`). No injection surface.
- **Sensible schema constraints:** `UNIQUE(user_id, date)` on `usage_metrics`, and a singleton settings row enforced by `CHECK (id = 1)` (`data/schema.sql:26,42`). That makes a good talking point.
- **Explainable, deterministic score** with divide-by-zero guards and caps (`core/scorer.py:20,36`), plus unit tests that pin the math (`tests/test_scorer.py`).
- **Graceful degradation is at least attempted** for LLM rate limits and outages (`ai/guide_generator.py:62-80`), and for missing SMTP/Slack config (`notifications/email_report.py:103`, `slack_post.py:106`).
- **Demo-safe email routing:** `PRODUCTION_MODE` toggle sends all mail to one test inbox unless explicitly enabled (`email_report.py:155`).
- **Bounded SMTP timeout** (`timeout=10`) and Slack HTTP errors handled by type (`slack_post.py:129-140`).
- **Frontend reads `VITE_API_URL`** on Dashboard and EngineerDetail. It’s only Runbook that misses it.
- **Polished UI**, a multi-stage frontend Dockerfile (node build → nginx), and a Render blueprint. The project *looks* finished, which is why the gaps below matter.
- **The existing `DEVTELEMETRY_INTERVIEW_REPORT.md` is honest** about missing auth, the unused `ai_guides` table, and the undeployed scheduler. Keep that tone.

---

## 4. Findings

### [SEC-01] Side-effecting endpoints are unauthenticated on a public deployment
- Severity: **P0** | Interview Risk: **HIGH** | Confidence: **CONFIRMED** (code). Whether the live Render service has SMTP/Slack env vars set is SUSPECTED, not checked.
- Category: security
- Location: `api/routes.py:107-113` (`POST /trigger-alerts`), `api/routes.py:94-105` (`POST /settings`), `api/main.py:8-14` (CORS `*` with credentials)
- What’s wrong: Anyone who knows the URL can POST to `/api/trigger-alerts`. Each call runs `run_weekly_telemetry_check()`, which makes 11 SMTP logins and sends, one Slack post, and one Gemini call. `render.yaml:22-23` sets `PRODUCTION_MODE=true`, so the developer emails go to Faker-generated `first.last@company.com` addresses. `company.com` is a real third-party domain. `POST /settings` lets anyone rewrite the schedule.
- Evidence: There is no auth dependency on any route (`api/routes.py` imports `Depends` but never uses it). The frontend calls the endpoint with a bare `fetch` (`Dashboard.jsx:157`).
- Why it matters: A loop of `curl -X POST` can spam a real domain from your Gmail account (risking suspension), burn Gemini quota, and flood Slack. Interviewers will look at a live demo’s endpoints, and “anyone can trigger your email blast” is an instant red flag.
- Fix: Add a FastAPI dependency that checks an `X-Admin-Token` header against an env var on all mutating routes, and return 401 otherwise. Set `PRODUCTION_MODE=false` on the demo, or point synthetic emails at `example.com` (RFC 2606 reserved). Add a cooldown on trigger-alerts (e.g. reject if one ran in the last N minutes, tracked in DB). Tighten CORS to `FRONTEND_URL` and drop `allow_credentials`.
- Effort: S–M

### [ML-01] “Estimated cost” is a random number unrelated to usage
- Severity: **P0** | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: ML / core logic
- Location: `data/seed.py:76` (`round(random.uniform(5.0, 30.0), 2)`), also `core/scorer.py:72`. It’s consumed by the leaderboard, trends `total_cost`, emails, and Slack.
- What’s wrong: Cost is drawn independently of input/output/cache tokens and the Opus/Sonnet/Haiku mix. An engineer with 50k Haiku tokens can “cost” $29 while one with 400k Opus tokens “costs” $5.
- Evidence: Trace `seed.py:63-77`. `estimated_cost_usd` doesn’t reference any other field.
- Why it matters: The README’s pitch is cost reduction (“$150–250/dev/month”, “Haiku costs 15× less than Opus”). In the product, cost isn’t computed at all. “How do you calculate cost?” is about the second question anyone will ask.
- Fix: Add `core/pricing.py` with a per-model price table (input, output, cache-write, cache-read per MTok), sourced from Anthropic’s public pricing page and dated. Compute `cost = Σ_model mix_m × (in×p_in + out×p_out + cw×p_cw + cr×p_cr)`. Unit test it with hand-computed cases. Recompute in the seed and at ingestion, and never store a client-supplied cost.
- Effort: M

### [BUG-01] Runbook page calls `127.0.0.1:8000`, so it’s broken on the live demo
- Severity: **P0** | Interview Risk: **HIGH** | Confidence: **CONFIRMED** (code). I didn’t load the live site.
- Category: bug
- Location: `frontend/src/pages/Runbook.jsx:442`
- What’s wrong: Every other page uses `import.meta.env.VITE_API_URL`. Runbook hardcodes localhost, so on `devtelemetry-1.onrender.com` the browser asks the *visitor’s* machine for the AI tasks. The fetch fails, `catch` only logs, and the page renders an empty task list. The response status is never checked either.
- Why it matters: This is the AI feature and the one in the screenshot. A recruiter clicking through sees it empty.
- Fix: Create one `src/api.js` with `API_BASE` and a `getJSON()` helper that checks `res.ok`, and use it in all three pages. Add an error state in Runbook.
- Effort: S

### [BUG-02] AI failures are cached forever: one outage poisons every runbook until restart
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED (reproduced)**
- Category: bug / LLM
- Location: `api/routes.py:271-299` with `ai/guide_generator.py:62-80`
- What’s wrong: `generate_efficiency_guide` turns every exception into a *successful* return value (the fallback list). The route can’t tell success from fallback and stores it in `ai_task_cache`. The cache has no TTL, no date in the key, and no size bound.
- Evidence: With the generator patched to fail once and then succeed, the 1st call returned “AI Service Offline” and the 2nd call (Gemini healthy) still returned “AI Service Offline” from a `[CACHE HIT]`.
- Why it matters: A single 429 at deploy time leaves stale fallback text for that user until the process restarts. It also never refreshes when new daily data arrives.
- Fix: Have the generator raise or return a typed result (`ok`/`fallback`), and cache only `ok`. Key the cache by `(user_id, latest_date, severity, prompt_version)` and persist it in the existing unused `ai_guides` table (see UPG-01).
- Effort: S

### [CONC-01] `async def` route makes blocking Gemini + SQLite calls, freezing the whole server
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED (measured)**
- Category: performance / concurrency
- Location: `api/routes.py:273` (`async def get_personalized_tasks`), which calls sync `sqlite3` and sync `client.models.generate_content`
- What’s wrong: FastAPI runs `async def` handlers on the event loop. A blocking call inside one stalls every other request on that worker. Plain `def` handlers would run in the threadpool.
- Evidence: Under real uvicorn with Gemini latency simulated at 3 s, `/api/leaderboard` latency went from **0.01 s to 2.81 s** while one runbook request was in flight (script in the audit session).
- Why it matters: This is the classic FastAPI interview question. One slow LLM call makes the dashboard hang for everyone.
- Fix: Change it to `def` (simplest and correct), or use `await client.aio.models.generate_content(...)` with an async DB call. Add a timeout either way.
- Effort: S

### [ERR-01] Missing `GEMINI_API_KEY` crashes the whole API at import
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED (reproduced)**
- Category: error-handling
- Location: `ai/guide_generator.py:7` (`genai.Client(...)` at module import)
- What’s wrong: google-genai raises `ValueError: No API key was provided` when the client is constructed. Because `api/routes.py` imports the module, the leaderboard, trends, and settings (which don’t need AI) all go down, and so do the tests.
- Fix: Create the client lazily in a `get_client()` function. If the key is missing, AI endpoints return the documented fallback or 503 and everything else keeps working. Log a warning at startup.
- Effort: S

### [BUG-03] “All alerts successfully dispatched!” is shown even when every send failed
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED** (from reading)
- Category: error-handling
- Location: `notifications/email_report.py:129-130,179-180` (exceptions printed, not raised), `slack_post.py:138` (returns False, ignored), `data/alert_worker.py:59-60,104` (return values ignored), `api/routes.py:111`, `frontend/src/pages/Dashboard.jsx:160-161` (no `res.ok` check; `data.message || "Alerts sent successfully!"` shows success on a 500 whose body is `{detail}`)
- What’s wrong: Failures are swallowed at three layers, and the UI defaults to a success message.
- Why it matters: The system misreports its own state. “How would an operator know the weekly email failed?” has no answer today.
- Fix: Have senders return a result. The worker aggregates `{sent: n, failed: [...]}`, the endpoint returns it (207 or 502 when anything failed), and the UI shows real counts. Stop returning `str(e)` to clients, and log it instead.
- Effort: S–M

### [BUG-04] `python main.py` (README step 6) crashes on a fresh clone; two disconnected pipelines
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED (reproduced)**
- Category: bug / architecture
- Location: `main.py:13-18`, `core/scorer.py:42-81`, `data/seed.py:15`
- What’s wrong: When `engineers_data.json` is missing, `main.py` calls `generate_historical_data()`, which writes **SQLite**, then opens the JSON file and crashes. The JSON path comes from a *different* generator (`scorer.generate_mock_data`) with a different shape (`model_mix` nested) than the DB. So the “daily agent” the README showcases never touches the database the dashboard reads.
- Evidence: `FileNotFoundError: [Errno 2] No such file or directory: 'engineers_data.json'` in a clean `git archive` copy.
- Fix: Make `main.py` read the latest day from the DB through shared query functions, and delete the JSON path and `generate_mock_data`.
- Effort: M

### [ML-02] Synthetic data is i.i.d. noise, so rankings, “waste patterns” and trends mean nothing
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: ML / data
- Location: `data/seed.py:45-77`
- What’s wrong: Every engineer’s metrics are redrawn from the same uniform distributions every day. No engineer has stable habits, so today’s “bottom 2” are random, tomorrow they’re different people, and the 30-day trend line is flat by construction. The README claims the data is “modelled on Anthropic’s published enterprise benchmarks”, but nothing in the generator references a benchmark.
- Why it matters: The coaching story (“your cache ratio is low, here’s how to fix it”) only makes sense if habits persist. Interviewers who ask about the data will see this immediately.
- Fix: Use a persona-based generator: each engineer gets latent habit parameters (cache propensity, Opus propensity, compact rate) drawn once, daily values = persona + noise, an optional improvement drift after a guide is “sent”, a fixed RNG seed, and weekday/weekend volume. Then the leaderboard is stable and trends are real within the simulation.
- Effort: M

### [BUG-05] Trends and engineer history return the **oldest** 30 days, not the latest
- Severity: P1 | Interview Risk: MEDIUM | Confidence: **CONFIRMED (reproduced on local DB)**
- Category: bug
- Location: `api/routes.py:42-48` (`/trends`), `api/routes.py:147-154` (`/engineer/{id}/details`)
- What’s wrong: `ORDER BY date ASC LIMIT 30` keeps the first 30 rows. Your local DB spans 2026-04-30 → 2026-07-01, and `/trends` returns 04-30 → 05-29, so the dashboard KPI “latest” is a month stale.
- Fix: Use a subquery `ORDER BY date DESC LIMIT 30`, then re-sort ascending, or filter `WHERE date >= date(MAX(date), '-29 days')`. Add a test with 40 days of data.
- Effort: S

### [ARCH-02] Alert scheduling isn’t deployed; UI offers options the scheduler ignores
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: architecture / bug
- Location: `data/clock.py` (not referenced by `render.yaml`, `Dockerfile.backend`, or `docker-compose.yml`), `clock.py:41-45` (only Daily/Weekly), `Dashboard.jsx:443-444` (offers Biweekly/Monthly)
- What’s wrong: Saving a schedule in the dashboard persists a row that nothing reads in production. Even locally, Biweekly/Monthly never fire, times are compared in server-local time (UTC on Render), `last_run_date` lives in memory (a restart in the same minute double-sends), and `clock.py` must be run from inside `data/` because of `import alert_worker`, while `email_report.py` loads templates from CWD-relative `frontend/`.
- Fix: (a) Remove Biweekly/Monthly from the UI or implement them. (b) Store an IANA timezone with the schedule. (c) Pick one honest deployment model, e.g. an in-process APScheduler job started in FastAPI lifespan (single instance), or a Render Cron Job / GitHub Actions cron calling the authenticated trigger endpoint, with `last_run_at` stored in the DB for idempotency.
- Effort: M

### [TEST-01] Test suite is broken and not isolated; no CI
- Severity: P1 | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: testing
- Location: `tests/test_generator.py:5,30,58` (patches `ai.guide_generator.model`, which no longer exists since the SDK migration), `tests/test_api.py:5` (uses the developer’s real `data/usage.db` via CWD), venv missing `google-genai`, no `.github/workflows`
- What’s wrong: 3/10 backend tests fail, the venv can’t even collect 2 of 3 files, API tests depend on whatever is in the local DB, and nothing runs tests automatically. There are zero tests for alert_worker, notifications, settings, runbook caching, or severity tiers.
- Why it matters: Commit `1a62ac5` says “Added tests”. An interviewer who clones and runs `pytest` sees red.
- Fix: See Phase 0/3. Patch `ai.guide_generator.client`, use a `tmp_path` SQLite DB fixture via a `DB_PATH` env var, mock SMTP/Slack, and add GitHub Actions.
- Effort: M

### [VAL-01] No input validation on settings or severity
- Severity: P2 | Interview Risk: **HIGH** | Confidence: **CONFIRMED (reproduced)**
- Category: validation
- Location: `api/routes.py:82-85` (`AlertSchedule` all free `str`), `api/routes.py:271` (`severity: str` path param)
- Evidence: `POST /api/settings {"frequency":"Hourly","day":"Funday","time":"99:99"}` → 200 and persisted. `GET /api/runbook-tasks/anything-i-want/<uid>` → 200, triggers a real Gemini call and a new cache entry.
- Why it matters: Every distinct severity string is a fresh paid LLM call plus unbounded memory growth. The severity also comes from the client URL, so a user can request a “low” runbook while being critical.
- Fix: Use `Literal["Daily","Weekly"]`, a `Literal` weekday, a `time` regex/`datetime.time`, and `severity: Literal["low","moderate","critical"]`. Better still, derive severity server-side from rank and drop it from the URL.
- Effort: S

### [LLM-01] LLM output is parsed by line heuristics; no schema, timeout, retry, or persistence
- Severity: P2 | Interview Risk: **HIGH** | Confidence: CONFIRMED (code). Failure frequency is not measured.
- Category: LLM
- Location: `ai/guide_generator.py:37-60` (parses lines starting with a digit and `'. '`), `:66` (429 detected by substring match), `:38` (no timeout), `data/schema.sql:30-38` (`ai_guides` table never written), `ai/prompts.py` (empty file; prompts are inline f-strings)
- What’s wrong: Every task gets the title “Optimization Action”. Numbered lines like `10. …` work, but `1) …` or markdown lists fall back to one blob. There’s no check that advice references real numbers (the prompt asks for it), no prompt versioning, and no record of what was generated.
- Fix: See UPG-01 (structured output + Pydantic + retry/timeout + persistence + small eval set).
- Effort: M

### [ML-03] Scoring formula has design flaws an interviewer will probe
- Severity: P2 | Interview Risk: **HIGH** | Confidence: Formula behavior CONFIRMED. The cache-ratio semantics mismatch is LIKELY: verify against Anthropic’s usage docs (`input_tokens` vs `cache_read_input_tokens`).
- Category: ML
- Location: `core/scorer.py:17-37`
- What’s wrong:
  - The model mix weights Haiku 1.0, Sonnet 0.6, Opus 0.1 regardless of task, so someone using Haiku for everything (including architecture work) gets the maximum 30 points. README says “penalty for Opus on *simple* tasks”, but task complexity isn’t modeled.
  - In Anthropic’s API usage object, `input_tokens` excludes cached reads, so `cache_read / input_tokens` can exceed 1 (it’s capped). A hit ratio is normally `cache_read / (input + cache_read + cache_creation)`. The synthetic data hides this by generating `cache_read ≤ 0.9 × input`.
  - `output_tokens`, `cache_write_tokens`, and `git_commits` are collected but unused. README mentions “session length control”, which isn’t implemented.
  - The model-mix term isn’t capped (the test documents a score > 100 on bad input).
- Fix: Define the hit ratio on total prompt tokens, cap or validate the mix (sum ≈ 1), return the sub-score breakdown from the API, and write a one-paragraph rationale plus known limitations. Consider cost per commit as an outcome signal (clearly labeled as a proxy).
- Effort: S–M

### [BUG-07] Dashboard shows fabricated trend arrows and random sparklines
- Severity: P2 | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: bug / frontend
- Location: `frontend/src/pages/Dashboard.jsx:107-108` (`trend: index < 3 ? "up" : "down"`, `bars: Math.random()…`)
- What’s wrong: Top 3 always show “up” and everyone else “down”. The bars change on every refresh.
- Fix: Compute a real 7-day score delta per engineer server-side (one window query), or remove the widgets.
- Effort: S

### [PERF-02] Alert dispatch runs synchronously inside the HTTP request
- Severity: P2 | Interview Risk: MEDIUM | Confidence: LIKELY (from reading; not timed against real SMTP)
- Category: performance / resilience
- Location: `api/routes.py:107-113` → `alert_worker.py:59-60` → `email_report.py:169,119` (a new SMTP connection + login per email, 10 s timeout each), `slack_post.py:121` (`urlopen` with **no timeout**)
- What’s wrong: Worst case is about 11 × 10 s SMTP + Gemini + an unbounded Slack wait in one request. Proxies (Render ~100 s) or the browser may cut it off mid-dispatch, and a retry will double-send.
- Fix: Reuse one SMTP connection for all messages, add `timeout=10` to Slack, run dispatch via `BackgroundTasks`, and record a `dispatch_runs` row (status, counts) that the UI polls. An idempotency guard (one run per schedule window) prevents double-send.
- Effort: M

### [BUG-06] `seed.py` isn’t idempotent: each run adds 10 new engineers
- Severity: P2 | Interview Risk: MEDIUM | Confidence: **CONFIRMED (reproduced)**
- Category: bug / data
- Location: `data/seed.py:21-40` (new `uuid4` each run, `INSERT OR IGNORE` never collides)
- Evidence: The local DB has **30 engineers over 63 dates**. Two runs in a clean copy produce 20 engineers on the latest date. Ranks and “bottom 2” shift as runs accumulate, and the trends average mixes cohorts.
- Fix: Add a `--reset` flag that truncates tables, plus a fixed seed and deterministic IDs.
- Effort: S

### [ERR-02] DB connections leak; file paths depend on the working directory
- Severity: P2 | Interview Risk: MEDIUM | Confidence: CONFIRMED (code)
- Category: error-handling / maintainability
- Location: `core/db.py:6-16` (CWD-relative `data/usage.db`); `api/routes.py:282` (hardcodes `'data/usage.db'` and bypasses the helper); `alert_worker.py:15` and `clock.py:10` (`__file__`-relative); `email_report.py:56,71` (`FileSystemLoader('frontend')`)
- What’s wrong: `with sqlite3.connect(...) as conn` commits or rolls back but **does not close** the connection, so every request leaks a handle until GC. Starting uvicorn or `clock.py` from another directory silently creates or opens a different (empty) DB, or fails to find templates.
- Fix: Add a `config.py` that resolves paths from `Path(__file__)` plus an env override (`DB_PATH`), and use a context manager that closes (`contextlib.closing` or a small generator dependency). Every module uses it.
- Effort: S

### [ARCH-01] Dead, empty, and duplicated code
- Severity: P2 | Interview Risk: MEDIUM | Confidence: CONFIRMED
- Category: architecture
- Location:
  - `core/models.py`, `core/leaderboard.py`, `ai/prompts.py` are empty (0 bytes), though the README describes them.
  - `core/db.py:51` `get_daily_records` queries the nonexistent table `usage_data`.
  - `core/scorer.py:42-81` is a data generator inside the scoring module.
  - Severity-tier logic is implemented 3–4 times: `routes.py:131-136`, `alert_worker.py:46-51`, unused `Dashboard.jsx:56`, and a *different* rule in `main.py:68`.
  - Hardcoded `total_team_size = 10` at `routes.py:118`.
  - The `ai_guides` table is never used.
- Why it matters: An interviewer opening `core/leaderboard.py` from the README tree and finding an empty file hurts credibility more than not listing it.
- Fix: Create one `core/severity.py` and one `core/queries.py`, then delete or implement the empty modules.
- Effort: M

### [DOC-01] README describes a different project than the code
- Severity: P2 | Interview Risk: **HIGH** | Confidence: **CONFIRMED**
- Category: docs
- Location: `README.md`
- What’s wrong:
  - It says Gemini 1.5 Flash; the code uses `gemini-2.5-flash` (`guide_generator.py:10`).
  - It says Chart.js and React 18; the code uses Recharts and React 19.
  - It says Python 3.11; the Dockerfile uses 3.10 and the venv is 3.14.
  - The structure tree lists `frontend/guide.html` and `style.css`, plus `core/models.py` dataclasses, which are empty or nonexistent.
  - `CLAUDE_MIGRATION.md` and `LICENSE` are linked but missing.
  - The sample console output (“bottom 3”, “Sending manager report via email ✓”, costs like $1.84) can’t be produced by `main.py`, which does bottom 5, sends no email, and has costs ≥ $5.
  - “Dashboard updated at http://localhost:8000” is the JSON API, not the dashboard.
  - “Switch to Claude in 5 minutes” has no adapter behind it.
  - Roadmap ticks “FastAPI dashboard with Chart.js”.
- Fix: Regenerate the README from the code in Phase 7. Until then, remove claims that are false today.
- Effort: S

### [SEC-02] Email HTML templates render untrusted text without autoescaping
- Severity: P2 | Interview Risk: LOW | Confidence: LIKELY
- Category: security
- Location: `notifications/email_report.py:56,71` (`Environment(loader=...)` without `autoescape`), `frontend/email_template.html:14` (`{{ ai_team_summary }}`, which is LLM output), `dev_alert_template.html:15` (`{{ name }}`)
- Fix: `Environment(..., autoescape=select_autoescape(["html"]))`. One line.
- Effort: S

### [SEC-03] Vulnerable / unpinned dependencies
- Severity: P2 | Interview Risk: LOW | Confidence: CONFIRMED (npm audit output)
- Category: security / DX
- Location: `frontend/package-lock.json` (vite, react-router, postcss, nanoid: 4 high, 1 moderate); `requirements.txt` (no versions at all)
- Note: The vite advisories affect the dev server on Windows, not the static build. react-router ships to users. Python reachability wasn’t assessed because pip-audit isn’t installed.
- Fix: `npm audit fix` and re-run tests. Pin Python deps (`pip freeze` into `requirements.txt`, or `pip-tools` with a `requirements.in`).
- Effort: S

### [DX-01] Deployment configs have data-persistence traps
- Severity: P2 | Interview Risk: MEDIUM | Confidence: LIKELY (not executed)
- Category: DevOps
- Location: `docker-compose.yml:16-17` (bind-mounts `./data/usage.db`; if the host file doesn’t exist Docker creates a *directory* by that name and SQLite can’t open it, and if it does exist it shadows the DB seeded at build time); `Dockerfile.backend:13` (seeds at **build** time, so the data’s “latest date” is the build date and ages); Render free tier has an ephemeral filesystem, so saved settings are lost on restart (acknowledged in `render.yaml` comments).
- Fix: Seed at container start when the DB is empty (entrypoint), use a named volume in compose, and document the reset-on-restart behavior honestly (or add a Render disk).
- Effort: S

### [DX-02] Local environment is out of sync with requirements
- Severity: P2 | Interview Risk: LOW | Confidence: CONFIRMED
- Category: DX
- Location: `venv/` has `google-generativeai` (deprecated) and not `google-genai`; Python versions are inconsistent (3.10 Docker / 3.11 README / 3.14 venv)
- Fix: Recreate the venv from pinned requirements, add a `requirements-dev.txt` (pytest, ruff), and state one supported Python version.
- Effort: S

### [TEST-02] Importing the app loads real SMTP and Slack credentials into the test process *(found during Phase 0)*
- Severity: P2 | Interview Risk: MEDIUM | Confidence: CONFIRMED (code). No send was observed: the Phase 0 network guard blocks it.
- Category: testing / security
- Location: `notifications/email_report.py:8-15` and `notifications/slack_post.py:7-9` call `load_dotenv()` and read credentials into **module-level constants at import time**. Importing `api.routes` imports `data.alert_worker`, which imports both modules.
- What’s wrong: Any test that reaches `send_developer_alert`, `send_daily_report`, or `send_slack_summary` (for example a future `/trigger-alerts` test) would use the developer’s real Gmail app password and Slack webhook from `.env`. Because the values are captured at import, `monkeypatch.delenv` in a test has no effect.
- Fix: Read config at call time, or through a settings object, and have the test fixtures clear `EMAIL_*`/`SLACK_*`. Keep the socket guard as a backstop. Schedule this before TEST-01a in Phase 3; do it in Phase 1 if BUG-03’s tests touch the senders.
- Effort: S

### Status after Phase 1 (2026-10-03)
- **Fixed** (red→green tests, see FIX_LOG.md): SEC-01, ML-01, BUG-01, ERR-01, CONC-01, BUG-02, BUG-03, TEST-02. Remaining P0: none. Remaining P1: BUG-04, ML-02, BUG-05, ARCH-02 (Phase 2), TEST-01 (Phase 3).
- **New, fixed in TEST-02:** the Slack "Open Dashboard" button was hardcoded to `http://localhost:5173` (`notifications/slack_post.py`).
- **New, open (adds to ML-02 / DOC-01):** with real prices, the generator’s token volumes cost **$0.26–$1.75 per engineer-day**. The README’s “$13/developer/active day” benchmark and its sample output ($1.84–$14.20) don’t match the simulated data. Fix the persona generator’s volumes in ML-02 (with a source for them), or change the claim.
- **Operational, not code:** existing databases (your local `data/usage.db` and the deployed one) still contain the old random costs and `@company.com` emails until they are reseeded (`seed.py --reset` arrives with BUG-06). Before redeploying, set `ADMIN_TOKEN` and `FRONTEND_URL` on the Render backend and `VITE_API_URL` on the Render frontend. Without `FRONTEND_URL`, CORS will block the deployed dashboard.

---

## 5. Hygiene Bundle (P3)

- 16 ESLint `no-unused-vars` errors (unused lucide/recharts imports in `EngineerDetail.jsx`, `Runbook.jsx`, `Dashboard.jsx`).
- `print()` with emojis instead of `logging`, and `sys.stdout.reconfigure` in `main.py:6` to make emojis work on Windows.
- Bare `except: pass` in `email_report.py:135,185`, and `server` may be unbound in `finally` if `SMTP()` raises (swallowed by the bare except, but sloppy).
- Stray files: `frontend/src/test.txt`, `api/guide.txt`, `demo_commands.txt`, `frontend/README.md` (Vite boilerplate), and `interview_study_guide.md` in the repo root.
- Faker names like “Dr. Jane O'Neil” produce invalid emails (`seed.py:25`). Use `fake.unique.user_name()@example.com`.
- Frontend bundle > 500 kB, with no route-level code splitting. Low priority for a demo.
- `engineers_data.json` is untracked but in the Docker build context exclusion list. It goes away with BUG-04.
- Commit history: 7 commits, two titled “Final…”. Future work should use the one-commit-per-fix convention in the plan.

---

## 6. Things That Could Not Be Verified

| Item | How to verify |
|---|---|
| Whether the live Render backend has SMTP/Slack/Gemini env vars set (affects how severe SEC-01 is in practice) | Check the Render dashboard env vars. Don’t test by POSTing to the live endpoint. |
| Whether the live Runbook page is actually empty (BUG-01) | Open `https://devtelemetry-1.onrender.com/runbook/critical/<id>` with DevTools → Network and look for a request to `127.0.0.1:8000`. |
| Anthropic usage-field semantics for the cache ratio (ML-03) | Read the Anthropic prompt-caching docs (`usage.input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`). |
| Real SMTP timing for PERF-02 | Time `POST /trigger-alerts` locally with a test Gmail app password and PRODUCTION_MODE=false. |
| Docker compose behavior (DX-01) | `docker compose up --build` on a clean checkout without `data/usage.db`. |
| Python dependency CVEs | `pip install pip-audit && pip-audit -r requirements.txt` (I didn’t install it without asking). |

---

## 7. Things I Must NOT Claim in an Interview (current state)

- “It’s fully tested” or “it has CI.” *(updated after Phase 1)* There are now 78 backend tests (90% coverage of core/api/ai/notifications) and 13 frontend tests, but no CI runs them yet (Phase 3).
- “It shows how much each engineer spends.” *(updated after Phase 1)* Cost is now computed from token usage with dated list prices (ML-01 fixed), but the usage itself is synthetic, and the per-model split is an assumption (tokens allocated by model mix). Say “estimated from usage with list prices”.
- “It tracks Claude Code usage.” Nothing ingests real telemetry. All data is synthetic, and the generator produces i.i.d. noise, not benchmark-modeled behavior (ML-02).
- “Weekly alerts are scheduled in production.” The scheduler isn’t deployed (ARCH-02).
- “AI guides are persisted.” *(updated after Phase 1)* Only successful guides are cached now (BUG-02 fixed), but in process memory: lost on restart, not shared between workers. The `ai_guides` table is still unused (UPG-01).
- “Production-ready” or “it has user authentication.” *(updated after Phase 1)* Mutating endpoints now need a shared admin token (SEC-01 fixed), but there are no user accounts or roles, and the token sits in sessionStorage (XSS-readable).
- “Switching to Claude takes 5 minutes.” There’s no provider abstraction, and the referenced doc doesn’t exist.
- “Uses Gemini 1.5 Flash / Chart.js / React 18.” It doesn’t (DOC-01).
- “The trend arrows / sparklines show performance trends.” They’re hardcoded and random (BUG-07).
- Any percentage like “reduces cost by X%”. Nothing has been measured.
