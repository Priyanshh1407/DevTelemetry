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

### P0-2 — venv drift: tests couldn't even be collected (commit b0411b1)
Situation: The project venv was used to run the test suite.
Symptom: `ImportError: cannot import name 'genai' from 'google'` while collecting `test_api.py` and `test_generator.py`. Only the 4 scorer tests ran.
Investigation: `pip list` in the venv showed `google-generativeai 0.8.6` (the deprecated SDK) and no `google-genai`. The code imports `from google import genai` (the new SDK). `requirements.txt` had no versions, so nothing recorded which SDK the code was written against.
Root cause: The code moved to the new Gemini SDK, but the venv was never re-synced and the requirements were unpinned.
Fix: Removed the old SDK, installed from `requirements.txt`, and pinned all direct dependencies to the installed versions after checking each one's `Requires-Python` is ≥ 3.10 (the Dockerfile uses 3.10). Moved pytest out of the runtime requirements into `requirements-dev.txt` (pytest, pytest-cov, httpx, ruff), so the Docker image no longer ships test tools.
Verification: `venv/Scripts/python -m pytest` collects all files.
Trade-off / what I'd do at larger scale: Pinning only direct deps still lets transitive versions float. A full lockfile (`pip-tools` compile or `uv lock`) would make builds bit-for-bit reproducible.
Interview version: "My tests passed on my global Python but couldn't even be collected in the project venv. The venv still had Google's deprecated SDK while the code imported the new one, and requirements.txt had no versions, so nothing caught it. I pinned the direct dependencies, checked they all support the Python version in my Dockerfile, and split test tooling into a dev requirements file so production images stay lean."

### P0-3 — three different ideas of where the database lives (commit fad827c)
Situation: Making the API testable against a temporary database.
Symptom: There was no single place to redirect the DB. `core/db.py` used the CWD-relative `data/usage.db`, the runbook route opened its own `sqlite3.connect('data/usage.db')`, and `alert_worker.py` built a third, file-relative path.
Root cause: Connection logic was duplicated instead of going through the existing helper.
Fix: `core/db.py` resolves the path at call time from `DB_PATH` (env override) with a default based on `__file__`, so it no longer depends on the working directory. The runbook route and alert worker now use `get_db_connection()`. `clock.py` still has its own path and is handled under ERR-02 in Phase 2.
Verification: `test_db_path_points_at_tmp_db`. The full API suite runs against `tmp_path` databases.
Trade-off: Reading the env var on every connection is negligible for SQLite. A config object injected via FastAPI dependencies would be cleaner and comes with ERR-02.
Interview version: "Before I could test anything I had to find where the database came from, and there were three answers: two working-directory-relative paths and one file-relative path. I routed everything through one helper that reads a DB_PATH override, which made the app independent of where you launch it and let every test get its own throwaway database."

### P0-4 — test harness: isolated DB, mocked LLM, no network (commit 9d02a61)
What changed: `tests/conftest.py` adds:
- A per-test temporary DB with deterministic data (10 engineers, scores strictly increasing with index, so rank and severity are predictable).
- An autouse mock of the Gemini client.
- A socket guard that raises on any non-loopback connect.
- A session guard that fails the run if `data/usage.db` changes.
- A reset of the runbook route's module-level cache between tests.

`client` depends on `empty_db`, so no test can fall through to the real DB.
Why a socket guard: "0 network calls" is now enforced by the test run itself. If a future test accidentally reaches Gemini, SMTP, or Slack, it fails loudly instead of silently sending.
Workaround to remove later: The conftest forces `GEMINI_API_KEY=test-dummy-key` before import because `guide_generator.py` constructs the client at import time and raises without a key (ERR-01). Delete that line once Phase 1 makes the client lazy.

### P0-5 — 3 of 10 tests were failing (commit 4685c1c)
Symptom: `AttributeError: module 'ai.guide_generator' has no attribute 'model'` in all three generator tests.
Investigation: The tests used `@patch("ai.guide_generator.model")`, the old SDK's `GenerativeModel` object. After the SDK migration the module exposes `client` and calls `client.models.generate_content`, so the patch target no longer existed.
Root cause: The tests weren't updated when the SDK changed, and with no CI nobody noticed.
Fix: The tests use the shared `mock_gemini` fixture and configure `client.models.generate_content`. Added characterization tests for markdown stripping, the unnumbered-response path, the 429 fallback, and the generic-error fallback. The last one documents BUG-02: a failure returns a normal-looking task list.
Verification: red (3 failed) → green (7 passed) in `tests/test_generator.py`.
Interview version: "Three of my AI tests were failing, and the reason was that they mocked an object that stopped existing when I migrated SDKs. Mocks are coupled to the shape of the code they replace. That's why I now mock at one shared fixture, and why CI matters: it would have flagged this the day it broke."

### P0-6 — characterization tests (commit f1e4717)
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

### ERR-01 — a missing API key took the whole API down (commit 66b4238)
Situation: Starting the backend without `GEMINI_API_KEY` (fresh clone, CI, a misconfigured deploy).
Symptom: `ValueError: No API key was provided` at import. The leaderboard, trends, and settings (none of which use AI) were unreachable.
Investigation: A subprocess test imports the app with the key blanked and calls `/api/leaderboard`. The traceback pointed at `genai.Client(...)` at module level in `ai/guide_generator.py`, imported by `api/routes.py`.
Root cause: An optional dependency was initialized eagerly at import time, coupling the availability of every endpoint to one feature's configuration.
Fix: `get_client()` builds the client on first use and raises `AIUnavailableError` without a key. The generator already degrades to a fallback, so AI endpoints answer with a marked fallback and everything else works. The subprocess test is needed because the test process has already imported the module. Empty env values beat `.env`, because `load_dotenv` never overrides.
Verification: `test_api_boots_without_gemini_key` red → green; `test_missing_key_degrades_to_fallback_instead_of_raising`.
Interview version: "My API wouldn't even start without the Gemini key, even though only one feature uses it, because the client was created when the module was imported. I made it lazy, so a missing key now degrades one feature instead of taking down the dashboard. The general lesson is not to let optional dependencies fail your startup."

### CONC-01 — one slow LLM call froze every request (commit 2bcdae1)
Situation: The runbook endpoint calls Gemini, which can take seconds.
Symptom: While one runbook was generating, unrelated requests like the leaderboard hung.
Investigation: TestClient can't show this (each request gets its own event loop), so the test starts a real uvicorn server on loopback, stubs generation with a 1.5 s `time.sleep`, and times the leaderboard during it. Red: **1.32 s**, exactly the remaining sleep.
Root cause: The handler was `async def` but called blocking code (sqlite3, the sync Gemini SDK). FastAPI runs `async def` handlers directly on the event loop, so a blocking call stalls every request on that worker. Plain `def` handlers run in a threadpool.
Fix: Made the handler `def`, and gave the Gemini client a 15 s timeout with at most 2 attempts (SDK exponential backoff on 408/429/5xx), so worst-case wait is bounded. Alternative considered: keep `async def` and use `client.aio` plus an async DB driver. That's more change for no benefit at this scale, and the threadpool (default 40 threads) is enough.
Verification: `test_slow_runbook_generation_does_not_block_leaderboard` 1.32 s → **0.016 s**; `test_client_is_built_with_timeout_and_bounded_retries`.
Trade-off / larger scale: The threadpool caps concurrent blocking calls. At high concurrency, go fully async (async SDK client and DB driver) or move generation to a background job.
Interview version: "I measured that one slow LLM call made my leaderboard take 1.3 seconds instead of 16 milliseconds. The route was declared async but did blocking I/O, and in FastAPI that runs on the event loop and blocks everyone. Making it a sync def moves it to the threadpool. I wrote a regression test against a real server, because the test client hides this bug."

### BUG-02 — an outage got cached as if it were an answer (commit b72332d)
Situation: The runbook page caches AI tasks in memory to avoid repeat LLM calls.
Symptom: After one failed generation (429, timeout, no key), that engineer's runbook showed "AI Service Offline" until the server restarted, even after Gemini recovered. New daily data never refreshed a cached guide either.
Investigation: Red tests. Fail once then succeed → the second response was still the outage text, with 1 generate call instead of 2. Insert a newer day of data → still 1 call.
Root cause: The generator turned every exception into a normal-looking list, so the caller couldn't tell a fallback from an answer and cached both. The cache key `(user, severity)` ignored the data date.
Fix: The generator returns `GuideResult(tasks, source)` with `source` ∈ {ai, rate_limited, unavailable}. Only `ai` results are cached, keyed `(user_id, latest_metrics_date, severity)`. Rate limits are detected with `errors.APIError.code == 429` instead of substring matching on "429"/"quota". Responses include `source` so the UI can tell what it got.
Verification: `test_runbook_failed_generation_is_not_cached`, `test_runbook_cache_refreshes_when_newer_data_arrives`, `test_non_rate_limit_api_error_is_unavailable_not_rate_limited`.
Trade-off: The cache is still in-process (lost on restart, not shared between workers). UPG-01 persists guides in the `ai_guides` table.
Interview version: "My fallback looked exactly like a real answer, so my cache stored the outage. One rate-limit blip meant a user saw 'service offline' until I restarted the server. I made the generator return a typed result with its source, cached only real answers, and put the data date in the cache key so new data invalidates old advice."

### TEST-02 — tests could reach real SMTP and Slack (commit 3e9ed63)
Situation: Writing tests for the notification senders.
Symptom: With all email and Slack env vars removed, `send_developer_alert` still called SMTP and `send_slack_summary` still called `urlopen`. Red in 4/4 tests. This confirmed (beyond LIKELY) that the real `.env` contains SMTP credentials and a Slack webhook that were captured at import.
Root cause: `load_dotenv()` plus module-level constants (`SENDER_EMAIL = os.getenv(...)`) froze configuration at import, so `monkeypatch.delenv` had no effect. Only the Phase 0 socket guard stood between a test and a real email.
Fix: Config is read inside the functions, and an autouse fixture deletes EMAIL_*, SLACK_WEBHOOK_URL, PRODUCTION_MODE, FRONTEND_URL, and ADMIN_TOKEN for every test.
Also fixed (new finding): the Slack "Open Dashboard" button was hardcoded to `http://localhost:5173`. It now uses `FRONTEND_URL` like the emails (`test_slack_dashboard_button_uses_frontend_url`).
Interview version: "My tests could have emailed real people. The SMTP credentials were read into constants when the module loaded, so tests couldn't remove them. I only found out because I'd already blocked outbound sockets in tests. Reading config at call time made it controllable, and the socket guard stays as defense in depth."

### BUG-01 — the AI runbook was empty on the live site (commit ffce669)
Situation: Opening a runbook on the deployed dashboard.
Symptom: Empty task list. The page fetched `http://127.0.0.1:8000/...`, which is the visitor's own machine.
Investigation: A Vitest test stubs `VITE_API_URL=https://api.example.test` and asserts the requested URL. Red: `Received: "http://127.0.0.1:8000/api/runbook-tasks/moderate/eng-01"`. The default *is* 127.0.0.1, so without stubbing the env the test couldn't tell the two apart.
Root cause: Each page built its own fetch, and Runbook skipped the env var. No page except EngineerDetail checked `res.ok`.
Fix: `src/api.js` holds `API_BASE`, `getJSON`, and `postJSON`. It throws `ApiError` (with FastAPI's `detail`) on any non-2xx, including non-JSON error pages. All pages use it. Runbook has an error state, and the schedule-save toast no longer says "saved" when the save failed.
Verification: `Runbook.test.jsx` (2), `api.test.js` (5); `grep 127.0.0.1 frontend/src` → only the dev default in `api.js`.
Interview version: "My flagship page worked on my laptop and was empty in production, because one component hardcoded localhost. I centralized every API call in one client that reads the base URL from config and turns HTTP errors into exceptions, and I wrote a test that fails if any page bypasses it."

### BUG-03 — "All alerts successfully dispatched!" when nothing was sent (commit d97cb7e)
Symptom: With every SMTP send failing, the endpoint returned 200 and the success message. The Dashboard also showed "Alerts sent successfully!" for a 500, because the body had no `message` and that was the fallback string.
Investigation: Red tests with SMTP mocked. All sends failing → 200; nothing configured → "success"; no data → 200; an internal error → its message (including a file path) echoed to the client.
Root cause: Failures were swallowed at three layers. Senders printed and returned None, the worker ignored return values, and the endpoint hardcoded success.
Fix: Senders return `sent`/`failed`/`skipped`. The worker returns a summary (counts, failed recipients, digest and Slack status). The endpoint maps it to 200 `success`/`skipped`, 409 no data, or 502 with the summary when anything failed (502 because an upstream service failed, not the request). Unexpected errors are logged with the traceback and answered with a generic 500. The UI shows the server's real counts.
Verification: `tests/test_alerts.py` (6), sender return-value tests.
Interview version: "The system reported success no matter what happened. I made each layer return what actually happened and mapped that to honest status codes, including a 502 with per-recipient results for partial failure, so an operator can see exactly who didn't get their email."

### SEC-01 — anyone could trigger the email blast (commit 49c3951)
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

### ML-01 — cost was a random number (commit 0ce05d8)
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

### BUG-05 — the dashboard showed the oldest month, not the latest (commit 2e1065f)
Symptom: On the local DB (2026-04-30 → 07-01), `/trends` returned 04-30 → 05-29, so the "latest" KPI was a month stale.
Root cause: `ORDER BY date ASC LIMIT 30` keeps the first 30 rows. Same bug in engineer history.
Fix: Select the newest 30 in a subquery (`ORDER BY date DESC LIMIT 30`), then re-sort ascending for the chart.
Verification: The strict xfail from Phase 0 flipped to XPASS (so pytest failed until the marker was removed), plus a new history test.
Interview version: "Classic LIMIT bug: ascending order plus LIMIT gives you the oldest rows. I'd recorded it as an expected failure in strict mode before fixing anything, so the fix had to flip that test, and it now guards against regression."

### VAL-01 — any string was accepted as a schedule or severity (commit af39518)
Symptom: `{"frequency":"Hourly","day":"Funday","time":"99:99"}` was saved. Every made-up severity in the runbook URL was a new cache entry and a new paid Gemini call.
Fix: `Literal` types for frequency, weekday and severity, plus a 24-hour `HH:MM` pattern, so these return 422 before any work. **Biweekly/Monthly were removed** from the UI and API, because no scheduler ever implemented them. The frontend renders FastAPI's 422 detail list as "field: message".
Interview version: "Validation at the boundary is also cost control: an unvalidated path parameter let anyone mint new cache keys, and each one was a paid LLM call."

### BUG-06 — every seed run added a new team (commit cdd6201)
Symptom: The local DB had grown to 30 engineers over 63 dates.
Root cause: Fresh random UUIDs on every run; `INSERT OR IGNORE` never collided.
Fix: A seeded RNG (`random.Random` + `Faker.seed_instance`, default 42), deterministic IDs, `--reset` (keeps alert settings), and CLI flags. Email local parts are sanitized.
Verification: `tests/test_seed.py`: run twice gives 10 engineers, the same seed gives identical rows, and a different seed gives different rows.

### ML-02 — rankings were noise; the README benchmark was off by 15× (commit cdf8f2e)
Symptom: Every engineer-day was an independent uniform draw. The "bottom 2" matched the chronic worst performers at chance level (0.24 vs 0.20). Cost was $0.81/day against the $13/day the README cites. Rows were inconsistent, e.g. **4 /compact uses in a 2-session day** (hidden by the scorer's `min(ratio, 1)` cap).
Investigation: Fetched the source the README cites (https://code.claude.com/docs/en/costs): "~$13 per developer per active day … below $30 per active day for 90% of users". The claim was legitimate; the generator was wrong.
Fix: Each engineer gets persona habits drawn once (activity, cache hit ratio, Opus/Haiku share, /compact rate, sessions, output/write ratios, commit rate). Days add noise around them, weekends run at 35% volume, and /compact uses are binomial(sessions, rate). Volume is calibrated to the published figure.
Result: weekday mean $13.68, p90 $23.42. Bottom-2 stability is 0.71 averaged over seeds 1–5 (each seed 0.57–0.87).
**Finding, not tuned away:** A 30-seed sweep gave median stability 0.65. Almost all the remaining daily rank noise comes from the score's `compacts / sessions` term (within-engineer daily SD 7.1 points vs 1.6 for cache and 0.7 for mix). A binomial ratio over 2–7 sessions is genuinely that noisy, so this is a **scoring-formula issue for ML-03** (pool over a window), not something to hide by making the simulator less noisy. The stability test asserts the honest property (mean over 5 seeds ≥ 0.55, every seed above the old generator's 0.27) rather than one lucky seed ≥ 0.70.
Interview version: "My leaderboard ranked random noise. The 'worst performers' changed every day because each day was an independent random draw. I modeled engineers as personas with stable habits, calibrated volume to Anthropic's published $13-per-day figure, and measured rank stability. That measurement told me something I didn't expect: most of the remaining noise comes from my own scoring formula, which scores a ratio of tiny daily counts. That's a scoring fix, so I logged it instead of fudging the simulator to pass a threshold."

### ARCH-01 (partial, pulled forward) — one severity rule (commit aa8479b)
The top-5/bottom-2 rule existed in `routes.py`, `alert_worker.py`, an unused copy in `Dashboard.jsx`, and a different rule in `main.py`. `core/severity.py` now owns it. Behavior is unchanged (the Phase 0 boundary tests stayed green), plus unit tests that document the small-team quirk (≤ 6 engineers: nobody is critical). Done now so BUG-04 wouldn't add a fifth copy.

### BUG-04 — the "daily agent" ranked people who don't exist (commit 1e215b2)
Symptom: `python main.py` (README step 6) seeded SQLite, then opened `engineers_data.json` and crashed on every fresh clone. When the JSON existed (locally, untracked), it came from a different generator, so the agent ranked different people than the dashboard (red test: printed "Randy Perry", not the DB's best engineer).
Fix: `core/queries.latest_day_rows()` is shared by the agent and the alert worker. `without_pii()` strips email before anything goes to the LLM (tested). The JSON path and `generate_mock_data` are deleted.
Verification: an in-process ranking test, and a subprocess "fresh clone" test from an empty directory with no key: exit 0 with fallback guides. Also verified on a `git archive` copy.
Note: your local `engineers_data.json` is now unused; delete it whenever you like.

### ERR-02 — connections leaked; templates depended on the working directory (commit adbd08d)
Symptom: The audit claimed `with sqlite3.connect()` doesn't close. My first test said it did. I investigated instead of accepting either result: handlers run in a worker thread, and sqlite checks the *creating thread before the closed state*, so touching a closed connection from the test thread raised the thread error, which the test misread. With connections tracked using `check_same_thread=False`, 6 endpoints were confirmed leaking (Python 3.14 still doesn't close in `__exit__`).
Fix: `db_session()` commits on success, rolls back on error, and always closes. Every caller uses it. `/guide` now calls the LLM *after* its DB session ends instead of holding a connection open during generation. Email templates resolve from the module's location. The dead `get_daily_records` (it queried a non-existent table) is removed.
Interview version: "A test that passes for the wrong reason is worse than no test. My leak test passed because of an unrelated sqlite threading error. I proved the leak by making the closed state observable, then fixed it with a session context manager."

### SEC-02 — HTML injection in emails (commit c0d134e)
Jinja had no autoescape, so the LLM-written summary and engineer names went into email HTML raw (red: `<img onerror>` and `<script>` came through). Fixed with `select_autoescape(["html"])`; no template uses `|safe`.

### BUG-07 — fake trend arrows and random sparklines (commit 0d7ab18)
Symptom: The top 3 always showed "up" and everyone else "down". The Activity bars were `Math.random()`.
Fix: `/api/leaderboard` adds `score_change_7d` (latest minus the previous 7-day average; null without history) and `recent_activity` (7 days of prompt tokens) from **one window query**, not one query per engineer. The Dashboard shows the signed change and scales bars to the team's busiest day. The Phase 0 key-set characterization test caught the shape change and was updated on purpose.

### PERF-02 — background dispatch on a DB-enforced ledger (commits 572bda9, 032e3f4, af58e38)
Situation: Sending about a dozen emails (one SMTP login each, 10 s timeouts), a Slack post and a Gemini call happened inside the HTTP request, past typical proxy timeouts. A retry after a timeout would have sent everything twice. The Phase 1 single-flight lock lived in process memory.
Fix:
1. A `dispatch_runs` table. A **partial unique index** (`WHERE status = 'running'`) lets the database reject a second concurrent run (8-thread race: exactly 1). `UNIQUE(slot)` gives at-most-once per scheduled slot. The cooldown is measured from the last delivering run, so it survives restarts. A `running` row older than 15 minutes is marked `abandoned`. Check-and-insert happens under `BEGIN IMMEDIATE`.
2. `POST /api/trigger-alerts` returns **202 in 41 ms** with a `status_url`. The work runs as a BackgroundTask, and the Dashboard polls `GET /api/dispatch-runs/{id}` (1.5 s interval, 3 min cap). The startup lifespan applies the idempotent schema so older databases gain the table.
3. `SmtpSession`: **one login per dispatch** (was 11). A dropped connection is reopened once and the email retried. A connect/login failure fails the remaining emails fast instead of repeating a bad login against Gmail, but a single refused recipient still fails only that email. (I caught my own bug here: `SMTPException` subclasses `OSError`, so my first version would have broken the whole batch on one bad address.) Slack has a 10 s timeout.

Trade-offs: `BackgroundTasks` runs in the web process. If the process dies mid-dispatch, the run becomes `abandoned`, not retried, because email at-most-once beats duplicates. At higher volume this would move to a real job queue.
Interview version: "The send button did a minute of work inside one HTTP request, and a retry could double-send. I moved the work to a background task tracked in a dispatch table, and let the database enforce the invariants: a partial unique index means only one run can be 'running', even across processes, and a unique slot column means a scheduled alert can't go out twice. The endpoint went from blocking for the whole dispatch to answering in 41 milliseconds."

### ARCH-02 — scheduled alerts that actually fire (commit eb58ddc)
Situation: The saved schedule never fired in production. `clock.py` wasn't deployed, couldn't be imported from the package, compared the server's clock (UTC on Render) to the saved time, and kept "already ran" in memory. Render's free tier sleeps, so an in-process scheduler would miss its times.
Decision (developer's choice): a **GitHub Actions cron** every 15 minutes calls `POST /api/scheduled-tick`.
Fix:
- An IANA `timezone` in settings (validated with zoneinfo; defaults to UTC for older clients). `init_db` adds the column to existing DBs via an idempotent `ALTER TABLE`.
- `core/schedule.due_slot()`: the most recent occurrence in that timezone, if no older than a grace window (default 120 min) for late cron runs. DST moves the UTC time, not the wall-clock time (tested across the 2026-11-01 US change).
- The tick endpoint starts a `schedule` run for the due slot. Repeated ticks return `already_sent`. A tick during a manual dispatch returns `busy` without consuming the slot, so the next tick retries. Scheduled runs skip the manual cooldown.
- `.github/workflows/scheduled-alerts.yml` (no repo permissions; curl retries are safe because the endpoint is idempotent). `data/clock.py` is now a local runner of the same decision function. The Dashboard saves in the browser's timezone and shows it. `tzdata` is pinned.
Not verifiable from here: the workflow only runs from the default branch with the two secrets set (see "Before you deploy" in the report).
Interview version: "The free tier sleeps, so I made the scheduler external and the endpoint idempotent: GitHub pings it every 15 minutes, the API works out whether a slot in the admin's timezone is due, and a unique constraint guarantees each slot sends at most once, even if GitHub retries or runs late."

### DX-01 — Docker data handling (commit f662adc)
- The image seeded at **build** time (data aged until the next deploy). It now seeds at container start with `--if-empty`, which never touches existing data.
- Compose's bind mount of `./data/usage.db` made Docker create a *directory* when the file was missing. The DB is now at `DB_PATH=/app/db/usage.db` on a named volume.
- New finding, fixed: `.dockerignore` didn't exclude `*.db`, so a local `docker build` copied the developer's own database into the image.
- Runs as non-root, honors `$PORT`, takes the frontend `VITE_API_URL` as a build arg.
Verified: `docker compose config` is valid, and a simulated double start seeds once and skips once. **Not verified:** an actual image build/run, because the Docker daemon wasn't running.

---

## Phase 3 — Testing & CI (2026-10-03, branch `phase-3-ci`)

Baseline (end of Phase 2) → after:

| Check | Before | After |
|---|---|---|
| Backend tests | 168 | 192 |
| Frontend tests | 18 (4 files) | 23 (5 files) |
| Coverage (core, api, ai, notifications, data, main) | 94% | 96.4%, enforced ≥ 85% in CI |
| `ruff check .` | 45 findings with a personal global config; 8 with project-relevant rules | 0 (rules pinned in `ruff.toml`) |
| ESLint | 15 errors | 0 |
| CI | none | `.github/workflows/ci.yml`: Python 3.10 + 3.14, Node 22 |
| Off switch for GitHub Actions | none | repository variables per workflow, plus a guard test |
| CI verified on clean environments | n/a | `git archive` of HEAD, fresh venvs from pinned requirements: 192 passed on **3.10** and **3.14**; clean `npm ci`: lint 0, 23 tests, build OK |

### TEST-01c (part 1) — a lint baseline CI can enforce (commit 51d1793)
Finding: `ruff check .` reported 45 issues locally, mostly import order and `dict()` style. They came from a **personal user-level ruff config** on the developer's machine, because the project had none. CI would have used different rules, so "passes locally" would not have meant "passes in CI".
Fix: `ruff.toml` pins the project rules (pyflakes, serious pycodestyle errors, bugbear; target py310). The 8 real findings were fixed:
- exception chaining (`raise … from e`) for the HTTP errors raised inside `except` blocks;
- `zip(strict=True)`;
- unused imports;
- `generate_team_report` **swallowed API errors without logging**; it now logs them.

ESLint went from 15 errors to 0 (unused imports and props). These were pulled forward from the Phase 4 hygiene bundle because CI must start green.
Interview version: "My linter gave different answers on my machine and in CI, because a personal config was being picked up. Pinning the rules in the repo makes the result the same everywhere. That's the whole point of CI."

### TEST-01a — tests where the decisions are (commit 1a63aba)
Most of TEST-01a was already done during Phases 1–2: notifications with mocked SMTP and Slack, runbook caching, severity tiers. Coverage showed the remaining business logic with no tests:
- what the **worker** sends: rank, team size and severity per engineer for teams of 10, 7 and 3;
- the **waste-pattern diagnosis** in the manager digest (Opus > 50% wins over a low score);
- the engineer-detail **insight thresholds** on both sides;
- **Slack failure modes** (non-200, HTTP error carrying Slack's reason, unexpected error);
- **dispatch-run messages**.

These tests pin existing correct behaviour, so they passed immediately. To make sure they can fail, the Opus threshold was temporarily mutated (0.50 → 0.70) and the tests caught it.

### TEST-01b — Dashboard error state (commit da60add)
Symptom: With the backend down, or one endpoint returning 500, the Dashboard only logged to the console and rendered an **empty leaderboard that looked like a team with no data**.
Fix: An alert shows the API's message and a **Retry** button that re-runs the fetch. The first version reset state inside the effect; the react-hooks lint rule flagged it (extra cascading render), so the reset moved into the click handler.
Verification: network failure and a single endpoint's 500 both show the error (red before the fix), and Retry recovers. EngineerDetail, previously untested, now has tests for its rendering and its 404 message.

### TEST-01c (part 2) + OPS-01 — CI and the off switches (commit d31ae02)
CI runs on every push and pull request:
- **backend** on Python **3.10** (what `Dockerfile.backend` ships) and **3.14** (local dev): ruff, then pytest with an 85% coverage gate; the coverage table is written to the run's summary page;
- **frontend** on Node **22**: `npm ci`, ESLint, Vitest, production build.

Other settings: read-only `permissions`, a newer push cancels the outdated run, 15-minute timeouts, pip/npm caching. Actions are pinned to their current major versions (`checkout`, `setup-python` and `setup-node` at v7, confirmed from their release pages and READMEs). No secrets are needed, because the tests mock Gemini, SMTP and Slack and block outbound network. Node 20 reached end-of-life in April 2026, so the frontend Docker image moved to `node:22`, matching CI.

Off switches (developer request: "turn the GitHub Actions off"):
- Every job has `if: vars.<CI_ENABLED | SCHEDULED_ALERTS_ENABLED> != 'false' || github.event_name == 'workflow_dispatch'`. Setting the repository variable to `false` skips automatic runs while a manual **Run workflow** still works. Unset means on.
- `tests/test_workflows.py` fails if a job lacks its switch, a workflow file isn't registered, the manual trigger is missing, or write permissions are requested. Removing the switch from one job was caught and named the job.
- The README documents the variables, GitHub's Disable buttons, `[skip ci]` and the `gh` CLI commands.

**Not yet verified on GitHub:** CI hasn't run on github.com, because nothing has been pushed. Every step was reproduced locally on clean environments (see the table). The first real run happens when the branch is pushed.
Trade-offs: the 3.10 + 3.14 matrix doubles backend minutes (free for public repos) in exchange for testing both what ships and what you develop on. Push + pull_request means a branch with an open PR runs CI twice per push; accepted for simplicity.
Interview version: "CI runs both test suites on clean machines, on the Python version I ship and the one I develop on, with a coverage gate. It needs no secrets because every external service is mocked at the boundary. Each workflow has an off switch, a repository variable that skips automatic runs but still allows manual ones, and a test that parses the workflow files fails if a new job forgets the switch."

---

## Phase 4 — Architecture & Code Quality (2026-10-03, branch `phase-4-architecture`)

Decisions (developer): **token fields match Anthropic's `usage` semantics** (with a data migration), and the **`/compact` term is pooled over 7 days** (option 1, chosen after a walkthrough of the noise problem).

Baseline (end of Phase 3) → after:

| Check | Before | After |
|---|---|---|
| Backend tests | 192 | 220 (incl. 3 property tests × 2,000 random cases, 4 golden-prompt tests, 6 migration tests) |
| Frontend tests | 23 | 24 |
| Coverage | 96.4% | 96% (919 statements) |
| Bottom-2 stability, 30 simulated teams (median / worst) | 0.65 / 0.33 | **0.82 / 0.60** |
| Within-engineer daily SD of the discipline term | 7.07 pts | **2.44 pts** |
| Simulated weekday cost (mean / p90) | $13.68 / $23.42 | $12.73 / $22.19 (published: ~$13 / < $30) |
| `npm audit` | 5 shipped (4 high) + 6 dev | **0** |
| `pip-audit` (pinned runtime + dev, incl. transitive) | never run | **no known vulnerabilities** |
| Python in Docker / CI | 3.10 (EOL Oct 2026) / 3.10 + 3.14 | **3.13** / 3.13 + 3.14 |
| `print()` in server code | 29 calls | 0 (ruff `T20` enforces it) |

### ARCH-01 — prompts module and shared queries (commits 2a20c11, 5f381ae, 4cfaaff)
- **Golden-file tests first:** the exact text of all four prompts (three severities plus the team report) was snapshotted from the old code. The prompts then moved **verbatim** into `ai/prompts.py`, and the snapshots prove they're byte-identical. Changing a prompt is now a reviewed diff (`UPDATE_GOLDEN=1`), never a refactoring side effect. The snapshot also documents a quirk: top performers ("low") get the "slightly below average" nudge. That's left for UPG-01.
- `core/queries.latest_metrics_for_user()` replaces two copies of the same query. The empty `core/models.py` and `core/leaderboard.py` are deleted.
- The email template coloured the rank with its own `rank <= 5` rule, a hidden copy of the tier logic. It now follows the severity from `core/severity.py` (red test: a "moderate" engineer at rank 3 showed green).

### Privacy — the LLM gets metrics, never identity (commit b6c3940)
Found while consolidating queries: `/api/guide` and the CLI agent sent the engineer's **name** to Gemini (only email was stripped, and only in the CLI). `without_pii()` now removes name and email on every path to the LLM. The tests assert the prompts contain the metrics but no name or email (red before).

### BUG-08 — "Rank #1" for someone with no data today (commit 18a7f78)
Symptom: an engineer with history but no row on the latest day (a new hire, a missed sync) showed **Rank #1, low severity** on their details page.
Root cause: `current_rank = 1` was a default that was only overwritten if the loop found them.
Fix: rank comes from the shared `latest_day_rows()` query. Someone absent from that day gets `null`, and the page says "Not ranked today" / "No data today".

### ML-03a — token fields match Anthropic's API (commit 7353ecc)
Situation: in Anthropic's `usage` object, `input_tokens` counts **uncached** tokens only (`cache_read_input_tokens` and `cache_creation_input_tokens` are separate). This schema stored "prompt tokens including cache reads" in `input_tokens`, so the hit ratio and any future real-data ingestion didn't line up.
Fix:
- `input_tokens` is now uncached; total prompt = input + cache_read + cache_write; hit ratio = cache_read / total prompt.
- **Cache writes now count as misses.** Previously a day with half its prompt in cache writes still got all 40 cache points.
- Pricing bills each kind once at its own price. **Cost values are unchanged**, because the old code already billed `input − cache_read`, which is exactly the new `input_tokens`.
- **Data migration:** `schema_meta` markers drive one-time conversions inside `init_db`'s transaction. Old rows get `input -= cache_read`, then every score is recomputed whenever `SCORING_VERSION` differs.
- Dry run on a **copy of the developer's real database**: 900 rows converted, no negatives, costs unchanged, scores recomputed, the missing `timezone` column and new tables added, and a second run a no-op.

Interview version: "My schema used a different meaning for input tokens than Anthropic's API, which would have made real data ingestion subtly wrong. I aligned the fields and wrote a versioned, idempotent migration that runs on startup inside one transaction. I tested it on a copy of real data before trusting it, and it's tracked in a meta table so it can never run twice."

### ML-03b — measure the habit, not the dice roll (commit 36891e4)
Situation: the discipline term scored one day's `compacts / sessions`. With 2–7 sessions a day that's mostly luck (0/2, 1/2, 2/2 for the same habit). It carried almost all day-to-day rank noise, and the bottom 2 get "critical" emails.
Fix:
- The discipline term is pooled over the scored day plus up to 6 earlier days.
- Model-mix shares are normalized, so the score can't exceed 100 (Phase 0 had documented 106).
- `score_breakdown()` is returned by the details API, computed on the same window as the stored score (test: the parts' total equals the stored score).
- `SCORING_VERSION 3` makes existing databases rescore on startup.

Measured:
- discipline daily SD 7.07 → 2.44;
- bottom-2 stability over 30 simulated teams: median 0.65 → 0.82, worst 0.33 → 0.60;
- seeds 1–5 mean: 0.71 → 0.85 (the test threshold was raised to ≥ 0.75).

Property tests (2,000 random cases each): the score stays in [0, 100]; moving tokens from uncached to cache never lowers it; using `/compact` more never lowers it.
Trade-off: a real change in habit takes about a week to show fully.
Interview version: "I measured that one score component carried almost all the day-to-day ranking noise. It was a ratio of two to seven events a day, so the same habit could score 0, 15 or 30. Pooling it over a week cut that noise by two thirds and made the bottom-two list match the genuinely worst engineers 82% of the time instead of 65%. I fixed it in the formula, not by making the simulation less random, and the stability test now guards it."

`docs/scoring.md` (commit f95c18d) explains the formula, the field mapping, why the weights are judgment calls, and the known limitations (model mix ignores task difficulty, Goodhart's law for `/compact`, no outcome measure, simulated data).

### Hygiene — logging, not printing (commits 9560a0e, 76024d5)
Symptom (seen twice during Phases 2 and 4): under `pytest -s` some dispatch tests ended in `error`.
Root cause: the worker and notifiers `print()`ed emoji. On a console or redirected output using cp1252 that raised `UnicodeEncodeError` **inside the dispatch**, so nothing was sent. It would also hit anyone running the API on Windows with output redirected. Red test: a cp1252 stdout reproduced the crash.
Fix: server modules use loggers (a handler that can't encode a character reports it instead of raising into the caller). The CLIs keep `print` for their own output and configure logging. Ruff `T20` forbids `print` elsewhere. Stray notes and the Vite template README were removed.

### SEC-03 / DX-02 — dependencies and Python version (commits 17249e8, 259fd02)
- **npm:**
  - `npm audit fix` and `npm update` crashed with an internal error in npm 10.9.2 (`Cannot read properties of null (reading 'edgesOut')`), even after a clean `npm ci`.
  - Workaround: installed react-router-dom 7.18.4 and vite 8.3.2 explicitly, and applied the in-range transitive updates with npm 11 via `npx`.
  - Verified that `npm ci` with npm 10 (what CI uses) accepts the lockfile.
  - Result: **0 vulnerabilities**, shipped and dev.
- **Python:** `pip-audit` (first ever run, via `uvx`) found **no known vulnerabilities** in the pinned runtime and dev requirements. Docker moves to **python:3.13-slim**, because 3.10 reaches end-of-life in October 2026. 3.13 was chosen over the plan's 3.12 because it's supported until 2029. CI tests 3.13 and 3.14, and ruff targets py313. A clean 3.13 environment from the pinned requirements runs 219 passed at 96.4% coverage.

---

## Phase 6 — Interview Upgrades (2026-10-04, branch `phase-6-upgrades`)

Decisions (developer):
- **Evals:** offline in CI and tests (recorded replies), live runs only with approval before each one.
- **Provider:** Gemini only, behind an interface; the README's Claude claim is reworded.
- **Model:** the latest Gemini (`gemini-3.8-flash`), falling back to the latest Flash-Lite (`gemini-3.5-flash-lite`) when it is out of quota or overloaded.
- **Eval:** the free tier allows only 20 requests/day for 3.8 Flash, so the full v1 vs v2 comparison ran on Flash-Lite (its own quota), all 30 profiles. The 3.8 Flash v1 baseline (n=10) is kept.

Tests: 297 backend (from 219), 26 frontend; coverage 97%; ruff and ESLint clean.

### UPG-01 — grounded, structured, stored coaching + evals (commits 5ea3b0a, ac57d8b, 935af7f, b1fcdad, 827fda8, 3c14deb, b354ee0, 260a41c, f645b10, 8fb76e4, 05423f3, e3e371c)
**Before:**
- The guide was free text split into tasks by line heuristics.
- Failures were cached in process memory.
- Nothing was stored, and nobody knew whether the advice cited the engineer's real numbers.

**What was built:**
- **Provider interface** (`ai/providers.py`):
  - `GuideProvider.generate(prompt, json_schema)` returns text, token counts (thinking billed as output), latency and cost.
  - `GeminiProvider` is the only implementation.
  - The model is set with `GEMINI_MODEL`, default `gemini-3.8-flash` (Google's models page, 2026-10-01).
  - Prices are a dated schedule per model: 3.8 Flash is $0.75 / $3.75 per 1M tokens through 2026, then $1.50 / $7.50.
  - **Model fallback:** on 429 or 5xx, one retry on `GEMINI_FALLBACK_MODEL` (default `gemini-3.5-flash-lite`, $0.30 / $2.50). Free-tier quotas are per model, so the fallback has its own allowance. Bad requests don't switch models. A guide is stored and metered under the model that actually answered.
- **Prompt v2:**
  - Input: a FACTS block of computed metrics (points lost per area, weakest area, 7-day `/compact` rate), never identity.
  - Output: JSON validated by Pydantic (`CoachingGuide`: headline, 1–5 actions with a `focus` area).
  - Rules: cite only facts, start with the weakest area, one action count per tier.
- **Failure path:** invalid JSON gets one repair call that feeds back the validation error. If that also fails, the engineer gets a rule-based guide built from their own sub-scores, marked as fallback and not stored as a success.
- **Storage:** guides are stored in `coaching_guides`, keyed by (user, data date, severity, prompt version, model). Repeat views cost nothing, and changing the prompt or model regenerates.

**Eval harness** (`evals/`):
- 30 fixed profiles: 10 per weakest area, all tiers.
- Rule-based checks:
  - valid structure;
  - every cited number grounded in the inputs within rounding;
  - the first action targets the weakest area;
  - the action count.
- Live runs record replies so they can be replayed for free in CI.

**Result: v1 vs v2, live, gemini-3.5-flash-lite, all 30 profiles, same model (fallback off):**

| | v1 (old prompt) | v2 (structured) |
|---|---|---|
| Valid guide | 100% | 100% |
| First action targets the weakest area | **50%** | **100%** |
| Cited numbers grounded | 97.4% of 267 | 100% of 442 |
| Guides with no ungrounded number | 80% | 100% |
| Output tokens per guide | 188 | 340 |
| Latency p50 / p95 | 1.8 / 2.7 s | 2.1 / 2.8 s |
| List-price cost for 30 guides | $0.017 | $0.028 (~$0.0009 per guide) |

**What the numbers mean:**
- **The real gain is targeting.** v1 leads with caching almost regardless of the problem: by weakest area it targets cache 9/10, model mix 4/10 and `/compact` 2/10. v2 gets the weakest area as a fact and is told to start there.
- **Grounding: real but small.** Reviewing v1's 7 flagged numbers by hand, **1 is wrong**: p17 cites 3,032,848 cache-write tokens, while the actual value is 303,284. The rest are correct averages or sums, one true bound and one generic interval ("every 30 to 45 minutes"). v2 cites 65% more numbers, all grounded.
- **Cost:** v2 uses ~1.8x the output tokens, still under a tenth of a cent per guide.

**Earlier baseline (v1, gemini-3.8-flash, n=10):**
- Valid 100%, targeted 100%, 60% of guides with no ungrounded number.
- 0 invented numbers (3 correct averages, 2 true bounds).
- ~1,460 output tokens per guide (mostly thinking), p50 8.9 s.
- **The same prompt targets 100% on 3.8 Flash but 50% on Flash-Lite,** so prompt quality depends on the model. That's why every eval run is pinned to one model.

**Found by the evals themselves:**
- **Checker bugs, found by reviewing every flagged number before trusting a table:**
  - "11.53 million" was read as 11.53 (3.8 baseline 50% -> 60%);
  - "11 dollars and 91 cents" was read as two numbers, and "March 31st" as a metric (Flash-Lite v1 66.7% -> 80%).
  - Each is fixed with a test; all runs were re-scored from their recordings.
- The first live run was 18 × 429 and 2 × 503. The 429s were the free tier's **20 requests/day per model**, so live runs now retry capacity errors, stop after 3 profiles in a row still fail, and finish later with `--only-missing`.

**Honest limits:**
- 30 synthetic profiles, one model per comparison, one run each (no repeat runs to measure variance).
- Checks are rule-based: tone and helpfulness aren't measured, and "targets the weakest area" is judged by keywords.
- v2 is *given* the weakest area as a fact, so part of its targeting gain is the design, not the model trying harder. That's the point, but say it.

Interview version: "On the same model and the same 30 profiles, the structured prompt fixed targeting from 50% to 100%: the old prompt talked about caching to people whose problem was model choice. Grounding improved less than I expected, because when I reviewed every flagged number, most were my checker's mistakes, not the model's. I fixed three checker bugs before trusting the table, and the old prompt had one genuinely wrong number in 30 guides."

### UPG-04 — the app meters its own AI calls (commit 935af7f)
Every model request is recorded in `ai_requests`: purpose, outcome, tokens from the provider's usage metadata, latency, cost, prompt version and model.

`GET /api/ai-stats` returns:
- outcomes;
- cache hit rate;
- fallback rate;
- tokens and cost;
- cost per generated guide;
- p50/p95 latency.

The team memo is metered too.

### UPG-03 — explainable score, measured weight sensitivity (commit 71293fa)
- The engineer page shows points per area out of each maximum and names the area that lost the most points.
- `analysis/weight_sensitivity.py`: 30 simulated teams, each area weight moved ±20%. Mean Kendall τ 0.93–0.98. The bottom 2 are unchanged in 83–93% of teams, so in about 1 team in 10, a 20% weight change swaps who gets a "critical" alert. Written up in docs/scoring.md with that caveat.

### UPG-02 — telemetry ingestion API (commit 4af26c8)
`POST /api/ingest` (admin token): up to 1,000 records per request, with field names from Anthropic's usage object.

**Validation is per record:**
- Pydantic, unknown fields rejected.
- Checks: non-negative counts, shares sum to 1, `compact_uses ≤ sessions`, no future dates, no client-supplied cost or score, no duplicate keys in a batch.
- Rejected records come back by index with reasons; the rest are written.

**Server-side:**
- Cost is computed from the dated price table, and the version is stored per row (`cost_price_version`).
- Score is computed on write.
- The upsert is idempotent on (user, date).
- Affected engineers are rescored, because the 7-day `/compact` pool makes later days depend on a corrected earlier day.

**One path for all data:** the simulator writes through the same function, so synthetic data must pass the API's validation (a rejection raises).

**Measured on SQLite:** 10,000 records in 0.66 s (~15k/s), re-send 0.57 s, validation alone ~100k/s.

### Model update (commit 3c14deb)
- `gemini-2.5-flash` → `gemini-3.8-flash`.
- A partial v1 run on 2.5 (4 calls) was discarded so both prompts are compared on the same model.
- Actual spend so far: $0 (free tier). Reported costs are list-price equivalents.

### Phase 6 recheck against the plan (commit 81f4393)
- **Verification command:** the plan's `python -m evals.run --pipeline v2` crashed, because it replayed on 3.8 Flash, which has no v2 recordings. Evals now default to the model of the published comparison.
- **CI check:** CI now verifies that the committed recordings reproduce the committed results exactly.
- **Labels:** a free re-score had relabelled the published tables "replay". Tables now say the replies are recorded live calls, and a replay with unchanged numbers leaves them alone.

---

## Phase 7 — Ship & Document (2026-10-04, branch `phase-6-upgrades`)

Decisions (developer):
- no licence;
- push and open a PR into `main` (the developer merges);
- Render deploys the `deployment` branch;
- personal notes untracked but kept locally.

Tests: 309 backend, 33 frontend; coverage 97%; ruff and ESLint clean.

### /health and deploy config (commit 1493129)
- **`GET /health`:**
  - Reports whether the database is reachable, the scoring version, the latest data date, and whether AI is configured (a boolean, never the key).
  - Returns 503 with no internal details when the database is down.
- **render.yaml:**
  - Uses `/health` as the health check.
  - The dashboard service declares `VITE_API_URL`. Vite bakes it in at build time; without it the live dashboard calls `127.0.0.1`.

### Leftover from Phase 6: the app's own AI numbers (commit b0395d6)
Captured by running `main.py` twice on a throwaway database while 3.8 Flash was out of free-tier quota.

**Two bugs found:**
- **Latency was under-metered:** it was timed from the fallback call only, hiding the failed main-model attempt. Corrected numbers: p50 6.3 s, p95 30.7 s.
- **The 30 s tail:** every request paid the main model's retries and timeout before falling back.

**Fix:**
- Latency covers the whole wait.
- After a 429/5xx, the main model is skipped for 5 minutes.

**Measured on a fresh database:**
- p50 / p95: 2.1 / 5.3 s;
- $0.0010 per generated guide;
- cache hit rate 50% (the second run served all five guides from the database);
- fallback rate 0%.

### DOC-01: the README rewritten from the code (commits 28f18d0, 3440a0b)
**Removed:**
- an invented `main.py` run (dated 2024, claimed to send email);
- a sample guide with made-up savings percentages;
- an unsourced "$150–250 per developer per month";
- files that don't exist; Chart.js; the MIT badge.

**Added:**
- real `main.py` output;
- a Mermaid diagram of the real flow;
- the eval table and metering numbers, each with its caveat;
- an API table, quick starts and a config table;
- known limitations.

**Screenshots:** retaken with Playwright driving Edge, after UI-01.

### Fresh clone, README followed word for word (commit b80d5e5)
**Result:** API and dashboard working in about 4 minutes on Python 3.13 / Node 22 (target < 10).

**Found:**
- **Placeholder secrets in `.env.example`:** `ADMIN_TOKEN=generate_a_long_random_token` becomes a *public* admin password for anyone who copies the file and forgets to change it. The placeholder Gemini key made every guide a failed API call.
  - Fix: optional secrets are now empty (fail safe), and a test guards it.
- **Tab title:** it was Vite's "frontend".

### UI-01 (new finding): mock-up content shown as product (commits 7437852, 1793482)
**Found while retaking screenshots.** The Runbook showed:
- invented metrics: "MTTR: 4h", "Ratio 1:5", "> 85% token utilization";
- invented stakeholders with stock photos;
- "Cost anomaly +$1,420/hr";
- "Last triggered 2m 44s ago";
- "completing 3/5 tasks will automatically downgrade severity", which doesn't exist;
- buttons that only called `alert()`.

**Elsewhere:**
- The navigation had dead links (Analytics, AI Agents, NODES, SECURITY, Deploy Agent).
- The dashboard's "+1 this month" and "−4.2%" were constants, and EXPORT CSV was `href="#"`.
- The engineer avatar came from a made-up URL.

**Now:**
- **Runbook:** one component for every tier showing:
  - the engineer's real rank, score, biggest opportunity and cost;
  - the guide;
  - whether the guide is AI-generated or the rule-based fallback, and why.
- **Dashboard:** the spend change is the real change from the previous day, and EXPORT CSV downloads the leaderboard.
- **Navigation and avatars:** only real links; initials instead of avatars.
- **Tests:** they check that none of the invented content remains.

Interview version: "When I retook the screenshots I noticed the runbook page still had mock-up numbers from the design tool, like an MTTR, a cost anomaly, and fake stakeholders. They looked like product data, but nothing computed them. I replaced every one with real data or removed it, and added tests that fail if they come back. A dashboard that invents numbers undermines the numbers that are real."

### Not done in this phase
- **Live deploy:** it needs the PR merged and the `deployment` branch updated (developer).
- **Live checks:** `/health` on Render and the Runbook in DevTools. Locally they're verified on a fresh clone.
- **Re-running the interview report / mock interview:** the developer will do this later.

---

## Verification of Phases 0–7 (2026-10-04, commit 9583839)

**Method:** a new clone, a new Python 3.13 virtualenv from the pinned requirements, a clean `npm ci`, no `.env` (no API key, no secrets). Each phase was checked against its own acceptance criteria in UPGRADE_PLAN.md.

| Phase | Check | Result |
|---|---|---|
| 0 | `pytest` in the venv with network blocked; real `data/usage.db` untouched; ≥ 15 tests | 309 passed; usage.db mtime still 2026-07-01 11:58:33 (unchanged by any test run) |
| 1 | admin routes without a token → 401; no `127.0.0.1` in `frontend/src` except `api.js`'s dev default; app works without a Gemini key; a failed generation isn't cached; all-SMTP-failure isn't reported as success | all pass |
| 1 | cost vs tokens (Spearman, seeded data) | **0.883** (audit found ~0) |
| 1 | leaderboard latency while a guide generation blocks | **13 ms** max (plan target < 200 ms) |
| 2 | persona stability, trends window, `--reset` twice, 422 on bad input, trigger answers at once, one dispatch per slot | 47 tests pass |
| 2 | `git archive` → `seed.py --reset` → `main.py` with no key | exit 0; 5 rule-based guides |
| 2 | `docker compose up --build` (clean clone, no `.env`) | health OK, `ai_configured: false`, 10 engineers, admin routes 503 without a server token; dashboard pages load data in a browser |
| 3 | coverage gate ≥ 85% (`core/` + `api/` ≥ 80%); ESLint 0; Vitest; build; workflow switches | 97% total, **99%** core+api; ESLint 0; 33 tests; build OK; every job has its switch |
| 4 | tier decisions only in `core/severity.py`; property tests; `npm audit`; `pip-audit`; ruff | all clean; 0 npm vulnerabilities (prod and dev); pip-audit "No known vulnerabilities" |
| 6 | `pytest && python -m evals.run --pipeline v2` | passes; reproduces the published table (targeting 100%, grounded 100%); tree unchanged |
| 7 | README followed on a fresh clone | API + dashboard working in ~4 min |

**Found and fixed by this verification:**
- **No key reported as an outage:** running without a Gemini key (documented as supported) printed "System Offline" and logged errors. It's now reported as "not configured" (commit 3fecbf8).
- **Docker dashboard 404 on app routes:** it answered 404 for `/engineer/…` and `/runbook/…`, so the runbook links in alert emails broke in Docker. Fixed with `frontend/nginx.conf`, verified live (commit 9583839).
- **Leaderboard latency threshold:** the concurrency test asserts < 0.5 s, looser than the plan's 200 ms. The measured value (13 ms) meets the plan; the threshold is left loose so the test doesn't flap on slow CI machines.

**Not verifiable locally (need GitHub / Render):**
- CI green on github.com;
- the OPS-01 switches on GitHub;
- the live deploy and live Runbook check.

### First CI run on GitHub (PR #1)
- **Failure:** backend failed on both Python versions with `ModuleNotFoundError: No module named 'core'` while loading `tests/conftest.py`. Frontend passed.
- **Root cause:** there was no pytest configuration. CI and the README run the plain `pytest` command, which does not put the repository root on the import path. Every local run (including the Phase 3 claim that all CI steps were reproduced, and the Phase 0–7 verification above) used `python -m pytest`, which does. **That claim was wrong in this one detail.**
- **Fix:** `pytest.ini` (`pythonpath = .`, `testpaths = tests`). Bare `pytest` with CI's exact flags passes on a clean clone: 309 tests, 97% coverage.
- **Lesson:** reproduce CI by running its exact command, not an equivalent one.
