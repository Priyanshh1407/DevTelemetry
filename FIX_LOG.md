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
