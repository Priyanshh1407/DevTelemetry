# FIX LOG

Debugging stories recorded as they happened. `<developer to fill>` marks things only you know.

---

## Phase 0 — Safety Net (2026-10-02, branch `phase-0-safety-net`)

Baseline → after:

| Check | Before | After |
|---|---|---|
| `pytest` in project venv | 2 collection errors (`cannot import name 'genai'`) | 35 passed, 2 xfailed (known bugs) |
| `pytest` in global Python | 7 passed, 3 failed | same 35 / 2 xfailed |
| Backend tests | 10 | 37 (35 + 2 strict xfail) |
| Coverage (core, api, ai) | not measured | 86% total; `routes.py` 95%, `guide_generator.py` 100% |
| Tests touching real `data/usage.db` | yes (`test_api.py` read it through a CWD-relative path) | no; enforced by a session guard (mtime unchanged: 2026-07-01 11:58:33) |
| Outbound network possible in tests | yes | blocked by a socket guard (proven by `test_outbound_network_is_blocked`) |

### P0-2 — venv drift: tests couldn't even be collected (commit d71b9ac)
Situation: The project venv was used to run the test suite.
Symptom: `ImportError: cannot import name 'genai' from 'google'` while collecting `test_api.py` and `test_generator.py`. Only the 4 scorer tests ran.
Investigation: `pip list` in the venv showed `google-generativeai 0.8.6` (the deprecated SDK) and no `google-genai`. The code imports `from google import genai` (the new SDK). `requirements.txt` had no versions, so nothing recorded which SDK the code was written against.
Root cause: The code moved to the new Gemini SDK, but the venv was never re-synced and the requirements were unpinned.
Fix: Removed the old SDK, installed from `requirements.txt`, and pinned all direct dependencies to the installed versions after checking each one's `Requires-Python` is ≥ 3.10 (the Dockerfile uses 3.10). Moved pytest out of the runtime requirements into `requirements-dev.txt` (pytest, pytest-cov, httpx, ruff), so the Docker image no longer ships test tools.
Verification: `venv/Scripts/python -m pytest` collects all files.
Trade-off / what I'd do at larger scale: Pinning only direct deps still lets transitive versions float. A full lockfile (`pip-tools` compile or `uv lock`) would make builds bit-for-bit reproducible.
Interview version: "My tests passed on my global Python but couldn't even be collected in the project venv. The venv still had Google's deprecated SDK while the code imported the new one, and requirements.txt had no versions, so nothing caught it. I pinned the direct dependencies, checked they all support the Python version in my Dockerfile, and split test tooling into a dev requirements file so production images stay lean."

### P0-3 — three different ideas of where the database lives (commit 8477616)
Situation: Making the API testable against a temporary database.
Symptom: There was no single place to redirect the DB. `core/db.py` used the CWD-relative `data/usage.db`, the runbook route opened its own `sqlite3.connect('data/usage.db')`, and `alert_worker.py` built a third, file-relative path.
Root cause: Connection logic was duplicated instead of going through the existing helper.
Fix: `core/db.py` resolves the path at call time from `DB_PATH` (env override) with a default based on `__file__`, so it no longer depends on the working directory. The runbook route and alert worker now use `get_db_connection()`. `clock.py` still has its own path and is handled under ERR-02 in Phase 2.
Verification: `test_db_path_points_at_tmp_db`. The full API suite runs against `tmp_path` databases.
Trade-off: Reading the env var on every connection is negligible for SQLite. A config object injected via FastAPI dependencies would be cleaner and comes with ERR-02.
Interview version: "Before I could test anything I had to find where the database came from, and there were three answers: two working-directory-relative paths and one file-relative path. I routed everything through one helper that reads a DB_PATH override, which made the app independent of where you launch it and let every test get its own throwaway database."

### P0-4 — test harness: isolated DB, mocked LLM, no network (commit a0dd073)
What changed: `tests/conftest.py` adds:
- A per-test temporary DB with deterministic data (10 engineers, scores strictly increasing with index, so rank and severity are predictable).
- An autouse mock of the Gemini client.
- A socket guard that raises on any non-loopback connect.
- A session guard that fails the run if `data/usage.db` changes.
- A reset of the runbook route's module-level cache between tests.

`client` depends on `empty_db`, so no test can fall through to the real DB.
Why a socket guard: "0 network calls" is now enforced by the test run itself. If a future test accidentally reaches Gemini, SMTP, or Slack, it fails loudly instead of silently sending.
Workaround to remove later: The conftest forces `GEMINI_API_KEY=test-dummy-key` before import because `guide_generator.py` constructs the client at import time and raises without a key (ERR-01). Delete that line once Phase 1 makes the client lazy.

### P0-5 — 3 of 10 tests were failing (commit aebe0ef)
Symptom: `AttributeError: module 'ai.guide_generator' has no attribute 'model'` in all three generator tests.
Investigation: The tests used `@patch("ai.guide_generator.model")`, the old SDK's `GenerativeModel` object. After the SDK migration the module exposes `client` and calls `client.models.generate_content`, so the patch target no longer existed.
Root cause: The tests weren't updated when the SDK changed, and with no CI nobody noticed.
Fix: The tests use the shared `mock_gemini` fixture and configure `client.models.generate_content`. Added characterization tests for markdown stripping, the unnumbered-response path, the 429 fallback, and the generic-error fallback. The last one documents BUG-02: a failure returns a normal-looking task list.
Verification: red (3 failed) → green (7 passed) in `tests/test_generator.py`.
Interview version: "Three of my AI tests were failing, and the reason was that they mocked an object that stopped existing when I migrated SDKs. Mocks are coupled to the shape of the code they replace. That's why I now mock at one shared fixture, and why CI matters: it would have flagged this the day it broke."

### P0-6 — characterization tests (commit 14f997e)
What changed: 22 API tests pin current responses for `/leaderboard`, `/trends`, `/engineer/{id}/details` (rank and severity at every tier boundary: ranks 1, 5, 6, 8, 9, 10), `/settings`, `/guide`, and `/runbook-tasks` (including the in-memory cache: 2 requests → 1 LLM call).
Known bugs recorded as strict xfails, verified to fail for the documented reason:
- BUG-05: with 40 days of data, `/trends` ends at `2026-01-30` instead of the latest `2026-02-09`.
- VAL-01: `{"frequency":"Hourly","day":"Funday","time":"99:99"}` → 200 instead of 422.

`strict=True` means that when the fix lands, the test XPASSes, pytest reports a failure, and the marker has to be removed, so the bug can't be fixed or regress silently.
Interview version: "Before changing behavior I wrote characterization tests: they assert what the system does today, not what it should do. For two bugs I already knew about, I wrote the correct assertion and marked it as an expected failure in strict mode, so fixing the bug forces me to flip the test, and it then guards against regression."

---

## Phase 1 — Critical Fixes (2026-10-03, branch `phase-1-critical-fixes`)

Baseline (end of Phase 0) → after:

| Check | Before | After |
|---|---|---|
| Backend tests | 35 passed, 2 xfailed | 78 passed, 2 xfailed (the xfails are BUG-05 and VAL-01, Phase 2) |
| Frontend tests | 3 | 13 |
| Coverage (core, api, ai, notifications) | 86% (without notifications) | 90% |
| Leaderboard latency while one runbook waits 1.5 s on the LLM | 1.32 s | 0.016 s |
| Concurrent "Send alerts" clicks (5 at once) | 5 dispatches | 1 dispatch (others 409/429) |
| Unauthenticated `POST /api/trigger-alerts` | 200, emails sent | 401 (503 if the server has no ADMIN_TOKEN) |
| Spearman(cost, input+output tokens) on seeded data | +0.059 | +0.613 (+0.742 vs uncached input + output) |
| API boots without `GEMINI_API_KEY` | no (`ValueError` at import) | yes |
| Real `data/usage.db` touched by tests | no | no (mtime still 2026-07-01 11:58:33) |

Order changed from the plan: ERR-01 → CONC-01 → BUG-02 → TEST-02 → BUG-01 → BUG-03 → SEC-01 → ML-01. BUG-01 (shared `api.js`) came before BUG-03 and SEC-01 so their UI changes could build on it.

### ERR-01 — a missing API key took the whole API down (commit 0821da7)
Situation: Starting the backend without `GEMINI_API_KEY` (fresh clone, CI, a misconfigured deploy).
Symptom: `ValueError: No API key was provided` at import. The leaderboard, trends, and settings (none of which use AI) were unreachable.
Investigation: A subprocess test imports the app with the key blanked and calls `/api/leaderboard`. The traceback pointed at `genai.Client(...)` at module level in `ai/guide_generator.py`, imported by `api/routes.py`.
Root cause: An optional dependency was initialized eagerly at import time, coupling the availability of every endpoint to one feature's configuration.
Fix: `get_client()` builds the client on first use and raises `AIUnavailableError` without a key. The generator already degrades to a fallback, so AI endpoints answer with a marked fallback and everything else works. The subprocess test is needed because the test process has already imported the module. Empty env values beat `.env`, because `load_dotenv` never overrides.
Verification: `test_api_boots_without_gemini_key` red → green; `test_missing_key_degrades_to_fallback_instead_of_raising`.
Interview version: "My API wouldn't even start without the Gemini key, even though only one feature uses it, because the client was created when the module was imported. I made it lazy, so a missing key now degrades one feature instead of taking down the dashboard. The general lesson is not to let optional dependencies fail your startup."

### CONC-01 — one slow LLM call froze every request (commit 9bb3890)
Situation: The runbook endpoint calls Gemini, which can take seconds.
Symptom: While one runbook was generating, unrelated requests like the leaderboard hung.
Investigation: TestClient can't show this (each request gets its own event loop), so the test starts a real uvicorn server on loopback, stubs generation with a 1.5 s `time.sleep`, and times the leaderboard during it. Red: **1.32 s**, exactly the remaining sleep.
Root cause: The handler was `async def` but called blocking code (sqlite3, the sync Gemini SDK). FastAPI runs `async def` handlers directly on the event loop, so a blocking call stalls every request on that worker. Plain `def` handlers run in a threadpool.
Fix: Made the handler `def`, and gave the Gemini client a 15 s timeout with at most 2 attempts (SDK exponential backoff on 408/429/5xx), so worst-case wait is bounded. Alternative considered: keep `async def` and use `client.aio` plus an async DB driver. That's more change for no benefit at this scale, and the threadpool (default 40 threads) is enough.
Verification: `test_slow_runbook_generation_does_not_block_leaderboard` 1.32 s → **0.016 s**; `test_client_is_built_with_timeout_and_bounded_retries`.
Trade-off / larger scale: The threadpool caps concurrent blocking calls. At high concurrency, go fully async (async SDK client and DB driver) or move generation to a background job.
Interview version: "I measured that one slow LLM call made my leaderboard take 1.3 seconds instead of 16 milliseconds. The route was declared async but did blocking I/O, and in FastAPI that runs on the event loop and blocks everyone. Making it a sync def moves it to the threadpool. I wrote a regression test against a real server, because the test client hides this bug."

### BUG-02 — an outage got cached as if it were an answer (commit dd01c97)
Situation: The runbook page caches AI tasks in memory to avoid repeat LLM calls.
Symptom: After one failed generation (429, timeout, no key), that engineer's runbook showed "AI Service Offline" until the server restarted, even after Gemini recovered. New daily data never refreshed a cached guide either.
Investigation: Red tests. Fail once then succeed → the second response was still the outage text, with 1 generate call instead of 2. Insert a newer day of data → still 1 call.
Root cause: The generator turned every exception into a normal-looking list, so the caller couldn't tell a fallback from an answer and cached both. The cache key `(user, severity)` ignored the data date.
Fix: The generator returns `GuideResult(tasks, source)` with `source` ∈ {ai, rate_limited, unavailable}. Only `ai` results are cached, keyed `(user_id, latest_metrics_date, severity)`. Rate limits are detected with `errors.APIError.code == 429` instead of substring matching on "429"/"quota". Responses include `source` so the UI can tell what it got.
Verification: `test_runbook_failed_generation_is_not_cached`, `test_runbook_cache_refreshes_when_newer_data_arrives`, `test_non_rate_limit_api_error_is_unavailable_not_rate_limited`.
Trade-off: The cache is still in-process (lost on restart, not shared between workers). UPG-01 persists guides in the `ai_guides` table.
Interview version: "My fallback looked exactly like a real answer, so my cache stored the outage. One rate-limit blip meant a user saw 'service offline' until I restarted the server. I made the generator return a typed result with its source, cached only real answers, and put the data date in the cache key so new data invalidates old advice."

### TEST-02 — tests could reach real SMTP and Slack (commit 98d0038)
Situation: Writing tests for the notification senders.
Symptom: With all email and Slack env vars removed, `send_developer_alert` still called SMTP and `send_slack_summary` still called `urlopen`. Red in 4/4 tests. This confirmed (beyond LIKELY) that the real `.env` contains SMTP credentials and a Slack webhook that were captured at import.
Root cause: `load_dotenv()` plus module-level constants (`SENDER_EMAIL = os.getenv(...)`) froze configuration at import, so `monkeypatch.delenv` had no effect. Only the Phase 0 socket guard stood between a test and a real email.
Fix: Config is read inside the functions, and an autouse fixture deletes EMAIL_*, SLACK_WEBHOOK_URL, PRODUCTION_MODE, FRONTEND_URL, and ADMIN_TOKEN for every test.
Also fixed (new finding): the Slack "Open Dashboard" button was hardcoded to `http://localhost:5173`. It now uses `FRONTEND_URL` like the emails (`test_slack_dashboard_button_uses_frontend_url`).
Interview version: "My tests could have emailed real people. The SMTP credentials were read into constants when the module loaded, so tests couldn't remove them. I only found out because I'd already blocked outbound sockets in tests. Reading config at call time made it controllable, and the socket guard stays as defense in depth."

### BUG-01 — the AI runbook was empty on the live site (commit 17d6a2f)
Situation: Opening a runbook on the deployed dashboard.
Symptom: Empty task list. The page fetched `http://127.0.0.1:8000/...`, which is the visitor's own machine.
Investigation: A Vitest test stubs `VITE_API_URL=https://api.example.test` and asserts the requested URL. Red: `Received: "http://127.0.0.1:8000/api/runbook-tasks/moderate/eng-01"`. The default *is* 127.0.0.1, so without stubbing the env the test couldn't tell the two apart.
Root cause: Each page built its own fetch, and Runbook skipped the env var. No page except EngineerDetail checked `res.ok`.
Fix: `src/api.js` holds `API_BASE`, `getJSON`, and `postJSON`. It throws `ApiError` (with FastAPI's `detail`) on any non-2xx, including non-JSON error pages. All pages use it. Runbook has an error state, and the schedule-save toast no longer says "saved" when the save failed.
Verification: `Runbook.test.jsx` (2), `api.test.js` (5); `grep 127.0.0.1 frontend/src` → only the dev default in `api.js`.
Interview version: "My flagship page worked on my laptop and was empty in production, because one component hardcoded localhost. I centralized every API call in one client that reads the base URL from config and turns HTTP errors into exceptions, and I wrote a test that fails if any page bypasses it."

### BUG-03 — "All alerts successfully dispatched!" when nothing was sent (commit a9c94f5)
Symptom: With every SMTP send failing, the endpoint returned 200 and the success message. The Dashboard also showed "Alerts sent successfully!" for a 500, because the body had no `message` and that was the fallback string.
Investigation: Red tests with SMTP mocked. All sends failing → 200; nothing configured → "success"; no data → 200; an internal error → its message (including a file path) echoed to the client.
Root cause: Failures were swallowed at three layers. Senders printed and returned None, the worker ignored return values, and the endpoint hardcoded success.
Fix: Senders return `sent`/`failed`/`skipped`. The worker returns a summary (counts, failed recipients, digest and Slack status). The endpoint maps it to 200 `success`/`skipped`, 409 no data, or 502 with the summary when anything failed (502 because an upstream service failed, not the request). Unexpected errors are logged with the traceback and answered with a generic 500. The UI shows the server's real counts.
Verification: `tests/test_alerts.py` (6), sender return-value tests.
Interview version: "The system reported success no matter what happened. I made each layer return what actually happened and mapped that to honest status codes, including a 502 with per-recipient results for partial failure, so an operator can see exactly who didn't get their email."

### SEC-01 — anyone could trigger the email blast (commit e8e6f4c)
Situation: The public deployment exposed `POST /api/trigger-alerts` (11 emails, a Slack post, and a Gemini call per hit) and `POST /api/settings` with no auth and CORS `*`.
Investigation: Red tests: no token → 200; and **5 concurrent triggers → 5 dispatches**.
Fix:
- `require_admin` dependency: `X-Admin-Token` checked against `ADMIN_TOKEN` with `secrets.compare_digest`. Fails closed (503) if the server has no token.
- `DispatchGuard`: a non-blocking lock gives single-flight (409 while running), plus a cooldown (429 with `Retry-After`) that starts only after a dispatch that delivered or attempted something. "Not configured" can be fixed and retried immediately.
- CORS limited to `FRONTEND_URL` and the Vite dev origins, no credentials, only the methods and headers used.
- The frontend `adminPost()` asks the admin for the token once and keeps it in `sessionStorage`. It's never in the bundle (anything in a Vite build is public). It's forgotten on 401/503.
- `render.yaml`: `PRODUCTION_MODE=false`, plus an `ADMIN_TOKEN` slot. Seeded emails moved from the real `company.com` domain to `example.com` (RFC 2606).

Why a shared token and not accounts: There are no users in this system. A single admin secret is proportionate. With real users it would be OIDC/session auth plus role checks, and the cooldown state would move from process memory to the DB or Redis.
Verification: `tests/test_security.py` (12), `api.test.js` adminPost tests (3).
Trade-off: `sessionStorage` is readable by any script on the page (XSS). An httpOnly cookie avoids that but brings CSRF handling. Acceptable for a single-admin demo; name the trade-off if asked.
Interview version: "My live demo had an unauthenticated endpoint that sends emails, and a test showed five simultaneous clicks sent five batches. I added an admin token that fails closed, a single-flight lock with a cooldown, and locked CORS to my frontend. I kept the token out of the JavaScript bundle on purpose, because anything shipped to the browser is public."

### ML-01 — cost was a random number (commit 9395fbb)
Symptom: `estimated_cost_usd = random.uniform(5, 30)` in the seed. Every dollar figure in the product was noise: Spearman(cost, tokens) **+0.059** on a 300-row seeded DB (measured with a scratch script that seeds a temp DB with `random.seed(42)`).
Fix: `core/pricing.py` holds a dated price table (`PRICE_TABLE_VERSION = "2026-09-25"`, Anthropic list prices: Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 4.5 $1/$5 per MTok; 5-minute cache writes at 1.25× input; cache reads $0.20 / $0.20 / $0.10). `estimate_cost()` bills uncached input, output, cache reads, and cache writes per model, weighted by the normalized model mix, and rejects negative or empty input. The seed and the legacy JSON generator use it.
Stated assumptions: `input_tokens` includes cache reads (matching how the scorer computes hit ratio), and daily tokens are split across models by the mix. Both are revisited in ML-03 / UPG-02.
Verification: 11 tests with hand-computed values (e.g. a 50/50 Opus/Haiku day = 0.5×1.32 + 0.5×0.335). After: Spearman **+0.613** vs tokens, **+0.742** vs uncached input + output, **+0.184** vs Opus share (was +0.015).
Consequence worth knowing: Daily costs are now **$0.26–$1.75** per engineer, not $5–$30, because that's what the simulated token volumes cost. The README's "$13/developer/day" benchmark therefore doesn't match the generator (see the audit report addendum).
Interview version: "The cost column in my dashboard was literally a random number. I replaced it with a dated per-model price table that bills uncached input, output, and cache reads and writes separately. Correlation between cost and usage went from essentially zero to 0.74. It also exposed that my synthetic data produced about a dollar a day, not the thirteen my README claimed, so I'm fixing the data rather than the claim."

---

## Phase 2 — Correctness & Resilience (2026-10-03, branch `phase-2-correctness`)

Baseline (end of Phase 1) → after:

| Check | Before | After |
|---|---|---|
| Backend tests | 78 passed, 2 xfailed | 168 passed, 0 xfailed |
| Frontend tests | 13 | 18 |
| Coverage (core, api, ai, notifications, data, main) | 90% (no data/main) | 94% |
| `/trends` with 40 days of data ends at | 2026-01-30 (oldest window) | 2026-02-09 (latest) |
| Engineers after running `seed.py` twice | 20 | 10 (deterministic IDs) |
| Bottom-2 stability (mean, seeds 1–5; chance = 0.20) | 0.24 | 0.71 (30-seed median 0.65) |
| Simulated weekday cost per engineer | mean $0.81 | mean $13.68, p90 $23.42 (published: ~$13, 90% < $30) |
| Spearman(cost, tokens) on seeded data | +0.613 | +0.895 (+0.938 vs uncached input + output) |
| Fresh clone `python data/seed.py --reset && python main.py` | FileNotFoundError | exit 0 |
| `POST /api/trigger-alerts` latency (dispatch takes 3 s) | ≈ the whole dispatch | 41 ms (202, then poll) |
| SMTP logins per dispatch (10 engineers) | 11 | 1 |
| Scheduled alerts in production | never fired | GitHub Actions tick → idempotent endpoint (needs merge to main + secrets) |
| DB connections left open per request | 1 (sqlite `with` never closes) | 0 |

Decision recorded: **ARCH-02 uses a GitHub Actions cron** calling an authenticated tick endpoint (chosen by the developer over APScheduler, a Render Cron Job, or removing scheduling).

### BUG-05 — the dashboard showed the oldest month, not the latest (commit e4ef771)
Symptom: On the local DB (2026-04-30 → 07-01), `/trends` returned 04-30 → 05-29, so the "latest" KPI was a month stale.
Root cause: `ORDER BY date ASC LIMIT 30` keeps the first 30 rows. Same bug in engineer history.
Fix: Select the newest 30 in a subquery (`ORDER BY date DESC LIMIT 30`), then re-sort ascending for the chart.
Verification: The strict xfail from Phase 0 flipped to XPASS (so pytest failed until the marker was removed), plus a new history test.
Interview version: "Classic LIMIT bug: ascending order plus LIMIT gives you the oldest rows. I'd recorded it as an expected failure in strict mode before fixing anything, so the fix had to flip that test, and it now guards against regression."

### VAL-01 — any string was accepted as a schedule or severity (commit 93c455c)
Symptom: `{"frequency":"Hourly","day":"Funday","time":"99:99"}` was saved. Every made-up severity in the runbook URL was a new cache entry and a new paid Gemini call.
Fix: `Literal` types for frequency, weekday and severity, plus a 24-hour `HH:MM` pattern, so these return 422 before any work. **Biweekly/Monthly were removed** from the UI and API, because no scheduler ever implemented them. The frontend renders FastAPI's 422 detail list as "field: message".
Interview version: "Validation at the boundary is also cost control: an unvalidated path parameter let anyone mint new cache keys, and each one was a paid LLM call."

### BUG-06 — every seed run added a new team (commit f67af7f)
Symptom: The local DB had grown to 30 engineers over 63 dates.
Root cause: Fresh random UUIDs on every run; `INSERT OR IGNORE` never collided.
Fix: A seeded RNG (`random.Random` + `Faker.seed_instance`, default 42), deterministic IDs, `--reset` (keeps alert settings), and CLI flags. Email local parts are sanitized.
Verification: `tests/test_seed.py`: run twice gives 10 engineers, the same seed gives identical rows, and a different seed gives different rows.

### ML-02 — rankings were noise; the README benchmark was off by 15× (commit dd119f6)
Symptom: Every engineer-day was an independent uniform draw. The "bottom 2" matched the chronic worst performers at chance level (0.24 vs 0.20). Cost was $0.81/day against the $13/day the README cites. Rows were inconsistent, e.g. **4 /compact uses in a 2-session day** (hidden by the scorer's `min(ratio, 1)` cap).
Investigation: Fetched the source the README cites (https://code.claude.com/docs/en/costs): "~$13 per developer per active day … below $30 per active day for 90% of users". The claim was legitimate; the generator was wrong.
Fix: Each engineer gets persona habits drawn once (activity, cache hit ratio, Opus/Haiku share, /compact rate, sessions, output/write ratios, commit rate). Days add noise around them, weekends run at 35% volume, and /compact uses are binomial(sessions, rate). Volume is calibrated to the published figure.
Result: weekday mean $13.68, p90 $23.42. Bottom-2 stability is 0.71 averaged over seeds 1–5 (each seed 0.57–0.87).
**Finding, not tuned away:** A 30-seed sweep gave median stability 0.65. Almost all the remaining daily rank noise comes from the score's `compacts / sessions` term (within-engineer daily SD 7.1 points vs 1.6 for cache and 0.7 for mix). A binomial ratio over 2–7 sessions is genuinely that noisy, so this is a **scoring-formula issue for ML-03** (pool over a window), not something to hide by making the simulator less noisy. The stability test asserts the honest property (mean over 5 seeds ≥ 0.55, every seed above the old generator's 0.27) rather than one lucky seed ≥ 0.70.
Interview version: "My leaderboard ranked random noise. The 'worst performers' changed every day because each day was an independent random draw. I modeled engineers as personas with stable habits, calibrated volume to Anthropic's published $13-per-day figure, and measured rank stability. That measurement told me something I didn't expect: most of the remaining noise comes from my own scoring formula, which scores a ratio of tiny daily counts. That's a scoring fix, so I logged it instead of fudging the simulator to pass a threshold."

### ARCH-01 (partial, pulled forward) — one severity rule (commit 5c82a18)
The top-5/bottom-2 rule existed in `routes.py`, `alert_worker.py`, an unused copy in `Dashboard.jsx`, and a different rule in `main.py`. `core/severity.py` now owns it. Behavior is unchanged (the Phase 0 boundary tests stayed green), plus unit tests that document the small-team quirk (≤ 6 engineers: nobody is critical). Done now so BUG-04 wouldn't add a fifth copy.

### BUG-04 — the "daily agent" ranked people who don't exist (commit acdd3f3)
Symptom: `python main.py` (README step 6) seeded SQLite, then opened `engineers_data.json` and crashed on every fresh clone. When the JSON existed (locally, untracked), it came from a different generator, so the agent ranked different people than the dashboard (red test: printed "Randy Perry", not the DB's best engineer).
Fix: `core/queries.latest_day_rows()` is shared by the agent and the alert worker. `without_pii()` strips email before anything goes to the LLM (tested). The JSON path and `generate_mock_data` are deleted.
Verification: an in-process ranking test, and a subprocess "fresh clone" test from an empty directory with no key: exit 0 with fallback guides. Also verified on a `git archive` copy.
Note: your local `engineers_data.json` is now unused; delete it whenever you like.

### ERR-02 — connections leaked; templates depended on the working directory (commit b967d84)
Symptom: The audit claimed `with sqlite3.connect()` doesn't close. My first test said it did. I investigated instead of accepting either result: handlers run in a worker thread, and sqlite checks the *creating thread before the closed state*, so touching a closed connection from the test thread raised the thread error, which the test misread. With connections tracked using `check_same_thread=False`, 6 endpoints were confirmed leaking (Python 3.14 still doesn't close in `__exit__`).
Fix: `db_session()` commits on success, rolls back on error, and always closes. Every caller uses it. `/guide` now calls the LLM *after* its DB session ends instead of holding a connection open during generation. Email templates resolve from the module's location. The dead `get_daily_records` (it queried a non-existent table) is removed.
Interview version: "A test that passes for the wrong reason is worse than no test. My leak test passed because of an unrelated sqlite threading error. I proved the leak by making the closed state observable, then fixed it with a session context manager."

### SEC-02 — HTML injection in emails (commit 9c75cd9)
Jinja had no autoescape, so the LLM-written summary and engineer names went into email HTML raw (red: `<img onerror>` and `<script>` came through). Fixed with `select_autoescape(["html"])`; no template uses `|safe`.

### BUG-07 — fake trend arrows and random sparklines (commit 0237063)
Symptom: The top 3 always showed "up" and everyone else "down". The Activity bars were `Math.random()`.
Fix: `/api/leaderboard` adds `score_change_7d` (latest minus the previous 7-day average; null without history) and `recent_activity` (7 days of prompt tokens) from **one window query**, not one query per engineer. The Dashboard shows the signed change and scales bars to the team's busiest day. The Phase 0 key-set characterization test caught the shape change and was updated on purpose.

### PERF-02 — background dispatch on a DB-enforced ledger (commits 193ec20, 90c914a, e1f2c3f)
Situation: Sending about a dozen emails (one SMTP login each, 10 s timeouts), a Slack post and a Gemini call happened inside the HTTP request, past typical proxy timeouts. A retry after a timeout would have sent everything twice. The Phase 1 single-flight lock lived in process memory.
Fix:
1. A `dispatch_runs` table. A **partial unique index** (`WHERE status = 'running'`) lets the database reject a second concurrent run (8-thread race: exactly 1). `UNIQUE(slot)` gives at-most-once per scheduled slot. The cooldown is measured from the last delivering run, so it survives restarts. A `running` row older than 15 minutes is marked `abandoned`. Check-and-insert happens under `BEGIN IMMEDIATE`.
2. `POST /api/trigger-alerts` returns **202 in 41 ms** with a `status_url`. The work runs as a BackgroundTask, and the Dashboard polls `GET /api/dispatch-runs/{id}` (1.5 s interval, 3 min cap). The startup lifespan applies the idempotent schema so older databases gain the table.
3. `SmtpSession`: **one login per dispatch** (was 11). A dropped connection is reopened once and the email retried. A connect/login failure fails the remaining emails fast instead of repeating a bad login against Gmail, but a single refused recipient still fails only that email. (I caught my own bug here: `SMTPException` subclasses `OSError`, so my first version would have broken the whole batch on one bad address.) Slack has a 10 s timeout.

Trade-offs: `BackgroundTasks` runs in the web process. If the process dies mid-dispatch, the run becomes `abandoned`, not retried, because email at-most-once beats duplicates. At higher volume this would move to a real job queue.
Interview version: "The send button did a minute of work inside one HTTP request, and a retry could double-send. I moved the work to a background task tracked in a dispatch table, and let the database enforce the invariants: a partial unique index means only one run can be 'running', even across processes, and a unique slot column means a scheduled alert can't go out twice. The endpoint went from blocking for the whole dispatch to answering in 41 milliseconds."

### ARCH-02 — scheduled alerts that actually fire (commit f14ae39)
Situation: The saved schedule never fired in production. `clock.py` wasn't deployed, couldn't be imported from the package, compared the server's clock (UTC on Render) to the saved time, and kept "already ran" in memory. Render's free tier sleeps, so an in-process scheduler would miss its times.
Decision (developer's choice): a **GitHub Actions cron** every 15 minutes calls `POST /api/scheduled-tick`.
Fix:
- An IANA `timezone` in settings (validated with zoneinfo; defaults to UTC for older clients). `init_db` adds the column to existing DBs via an idempotent `ALTER TABLE`.
- `core/schedule.due_slot()`: the most recent occurrence in that timezone, if no older than a grace window (default 120 min) for late cron runs. DST moves the UTC time, not the wall-clock time (tested across the 2026-11-01 US change).
- The tick endpoint starts a `schedule` run for the due slot. Repeated ticks return `already_sent`. A tick during a manual dispatch returns `busy` without consuming the slot, so the next tick retries. Scheduled runs skip the manual cooldown.
- `.github/workflows/scheduled-alerts.yml` (no repo permissions; curl retries are safe because the endpoint is idempotent). `data/clock.py` is now a local runner of the same decision function. The Dashboard saves in the browser's timezone and shows it. `tzdata` is pinned.
Not verifiable from here: the workflow only runs from the default branch with the two secrets set (see "Before you deploy" in the report).
Interview version: "The free tier sleeps, so I made the scheduler external and the endpoint idempotent: GitHub pings it every 15 minutes, the API works out whether a slot in the admin's timezone is due, and a unique constraint guarantees each slot sends at most once, even if GitHub retries or runs late."

### DX-01 — Docker data handling (commit 19ee73c)
- The image seeded at **build** time (data aged until the next deploy). It now seeds at container start with `--if-empty`, which never touches existing data.
- Compose's bind mount of `./data/usage.db` made Docker create a *directory* when the file was missing. The DB is now at `DB_PATH=/app/db/usage.db` on a named volume.
- New finding, fixed: `.dockerignore` didn't exclude `*.db`, so a local `docker build` copied the developer's own database into the image.
- Runs as non-root, honors `$PORT`, takes the frontend `VITE_API_URL` as a build arg.
Verified: `docker compose config` is valid, and a simulated double start seeds once and skips once. **Not verified:** an actual image build/run, because the Docker daemon wasn't running.
