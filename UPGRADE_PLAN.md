# UPGRADE PLAN
Target role(s): SDE + ML/AI Engineer (assumed) | Time budget: 3–4 weeks (assumed) | Based on audit #1 (2026-10-02)

## Strategy

DevTelemetry has a strong pitch (measure and coach AI-coding-tool token efficiency) and a polished UI, but the numbers under it are random, the AI path is fragile, and the public deployment exposes endpoints that send email. Today a deep-dive interview would turn into a list of things you’d have to admit.

For this project, “interview-ready” means four things:
1. Every number on screen is computed from usage by code you can explain.
2. The LLM feature degrades predictably and is measured.
3. Nothing on the public URL can be abused.
4. `git clone && pytest` is green in CI.

**Flagship upgrades:**
- **UPG-01 (main story, both roles):** Grounded, structured, persisted AI coaching with an eval harness. The talking point is a measured grounding/validity rate, not “I call Gemini”.
- **UPG-02 (SDE story):** A validated, idempotent telemetry ingestion API with a real pricing-based cost model. The synthetic generator becomes just one producer feeding the same pipeline real Claude Code data could use.

## Phase Overview

| Phase | Goal | Items | Effort | Interview payoff |
|---|---|---|---|---|
| 0 | Safety net | branch, pinned env, test DB fixture, fixed tests, characterization tests | ~1 day | “I made it testable before changing it” |
| 1 | Critical fixes | SEC-01, BUG-01, ML-01, ERR-01, CONC-01, BUG-02, BUG-03 | ~3 days | Auth, event-loop blocking, cache poisoning: three strong debugging stories |
| 2 | Correctness & resilience | BUG-04, BUG-05, BUG-06, ML-02, VAL-01, ARCH-02, PERF-02, ERR-02, BUG-07, SEC-02, DX-01 | ~4–5 days | Idempotent jobs, honest scheduling, realistic simulation |
| 3 | Testing & CI | TEST-01 completion, GitHub Actions, coverage on core, OPS-01 on/off switches | ~2 days | Green badge, mocked external services |
| 4 | Architecture cleanup | ARCH-01, ML-03, lint/hygiene, SEC-03, DX-02 | ~2 days | Single source of truth for severity and queries |
| 6 | Interview upgrades | UPG-01, UPG-02, UPG-03, UPG-04 | ~5–7 days | Eval numbers, ingestion contract, LLM cost tracking |
| 7 | Ship & document | README rewrite, diagram, deploy, re-run interview report | ~1.5 days | Honest, clickable demo |
| 8 | Measured features | UPG-05 coaching impact, UPG-06 what-if savings, UPG-07 anomaly detection, UPG-08 grounded team memo | ~5–7 sessions | A causal-inference story (regression to the mean), grounded savings, an evaluated detector |

Phase 5 (Performance) is merged away. The only real performance problems (CONC-01, PERF-02) are correctness/resilience issues and are fixed in Phases 1–2 with measured before/after numbers.

Total: roughly 18–21 working days, which fits 3–4 weeks.

---

## Phase 0 — Safety Net
Goal: Make the code safely changeable: reproducible environment, isolated test DB, and a green baseline that captures current behavior.
Why this order: Every later fix needs a red→green test, and tests need a DB they don’t share with your dev data and an LLM client that can be mocked.
Items:
- [x] P0-1 Commit the existing reports (`DEVTELEMETRY_INTERVIEW_REPORT.md`, this plan, the audit) on `deployment`, then `git checkout -b phase-0-safety-net` — S
- [x] P0-2 Recreate venv from `requirements.txt` (it currently has `google-generativeai`, not `google-genai`), pin versions (`pip freeze` → `requirements.txt`), add `requirements-dev.txt` (pytest, pytest-cov, ruff) — `requirements*.txt` — S
- [x] P0-3 Make the DB path configurable: `DB_PATH` env var with a `Path(__file__)`-based default in `core/db.py`; route `routes.py:282` through `get_db_connection` — `core/db.py`, `api/routes.py` — S
- [x] P0-4 `tests/conftest.py`: `tmp_path` DB fixture (init schema + small deterministic seed) and an autouse fixture that mocks the Gemini client so no test hits the network — `tests/conftest.py` — S
- [x] P0-5 Fix `tests/test_generator.py` to patch `ai.guide_generator.client` (it patches the nonexistent `model`) — S
- [x] P0-6 Characterization tests for `/leaderboard`, `/trends`, `/engineer/{id}/details`, `/settings` against the fixture DB — `tests/test_api.py` — M
Acceptance criteria:
- `pytest -q` passes in the venv (not only in global Python), with 0 network calls.
- `data/usage.db` is untouched by the test run (check its mtime).
- ≥ 15 backend tests.
Verification commands:
- `python -m venv venv && venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt`
- `venv/Scripts/python -m pytest -q --cov=core --cov=api --cov=ai`
Interview payoff:
- “Before fixing anything I made the system testable: injectable DB path, mocked LLM. Then I wrote characterization tests so refactors couldn’t silently change behavior.”
Risk / rollback:
- Low. Changes are additive except the DB path refactor. Revert the branch if needed.

## Phase 1 — Critical Fixes (P0 + HIGH-risk P1)
Goal: Close the public abuse path, make the AI feature work on the deployed site, and make cost a real computation.
Why this order: SEC-01 and BUG-01 affect the live demo today. ML-01 changes data that Phase 2’s persona generator and UPG-02 build on. ERR-01, CONC-01, BUG-02, and BUG-03 are small, HIGH-risk, and touch the same files.
Items:
- [x] SEC-01 Admin-token dependency on `POST /settings` and `POST /trigger-alerts`, plus a server-side cooldown on trigger; restrict CORS to `FRONTEND_URL`; set `PRODUCTION_MODE=false` on the demo and switch synthetic emails to `@example.com` — `api/main.py`, `api/routes.py`, `render.yaml`, `data/seed.py` — M (**touches auth: wait for “go”**)
- [x] BUG-01 Shared `frontend/src/api.js` (`API_BASE` + `getJSON` with `res.ok` check) used by all pages; error state in Runbook — `Runbook.jsx`, `Dashboard.jsx`, `EngineerDetail.jsx` — S
- [x] ML-01 `core/pricing.py` (per-model token prices with source URL and date) and `estimate_cost()`; seed uses it; unit tests with hand-computed values — `core/pricing.py`, `data/seed.py`, `tests/test_pricing.py` — M
- [x] ERR-01 Lazy Gemini client; app boots and non-AI endpoints work without `GEMINI_API_KEY` — `ai/guide_generator.py` — S
- [x] CONC-01 Runbook route no longer blocks the event loop (`def`, or async client) + LLM call timeout — `api/routes.py`, `ai/guide_generator.py` — S
- [x] BUG-02 Generator returns a typed result; only successes are cached; cache key includes latest data date — `ai/guide_generator.py`, `api/routes.py` — S
- [x] TEST-02 Read SMTP/Slack config at call time; fixtures clear real credentials (needed before BUG-03 tests touch senders) — `notifications/*`, `tests/conftest.py` — S
- [x] BUG-03 Senders return results; worker aggregates `{sent, failed}`; endpoint returns accurate status; UI checks `res.ok` and shows counts; no `str(e)` to clients — `notifications/*`, `data/alert_worker.py`, `api/routes.py`, `Dashboard.jsx` — S–M
Acceptance criteria:
- `POST /api/trigger-alerts` and `POST /api/settings` without the header → 401 (test).
- No `127.0.0.1` in `frontend/src` outside `api.js`’s dev default (`grep`).
- `estimate_cost` tests pass, and Spearman correlation between cost and total tokens in seeded data is > 0 (it’s ~0 today). Report the measured value.
- With `GEMINI_API_KEY` unset, `GET /api/leaderboard` → 200 (test).
- Concurrency test: leaderboard latency stays < 200 ms while a simulated 3 s runbook generation is in flight (baseline was 2.81 s; record the after number).
- Test: a failing generation is not cached; the next call retries.
- Test: when all SMTP sends fail, the endpoint does not report success.
Verification commands:
- `pytest -q`
- `grep -rn "127.0.0.1" frontend/src`
- `npm --prefix frontend run build && npm --prefix frontend test`
Interview payoff:
- Event-loop story with a real number (0.01 s → 2.81 s → fixed).
- Cache-poisoning story: “my fallback looked like success, so I cached an outage”.
- Auth: “why a static admin token is enough for this demo and what I’d use with real users”.
Risk / rollback:
- Auth could lock the demo UI out of its own trigger button. The frontend needs to send the token. Don’t ship the token in the public bundle; instead gate the trigger button behind a prompt or remove it from the public demo. Revert per-commit if needed.

## Phase 2 — Correctness & Resilience
Goal: Make the data meaningful, the queries correct, scheduling honest, and notification dispatch reliable.
Why this order: Depends on Phase 0 fixtures and Phase 1’s cost model. ML-02 makes the leaderboard stable, which BUG-07 (real trend deltas) needs.
Items:
- [x] BUG-05 Trends and history return the latest 30 days (test with 40 days of data) — `api/routes.py` — S
- [x] BUG-06 `seed.py --reset`, fixed RNG seed, deterministic engineer IDs — `data/seed.py` — S
- [x] ML-02 Persona-based synthetic generator (latent habits + noise + weekday effect), documented assumptions — `data/seed.py` (or `data/simulator.py`) — M
- [x] BUG-04 `main.py` reads from the DB via shared queries; delete the JSON path and `scorer.generate_mock_data` — `main.py`, `core/scorer.py` — M
- [x] VAL-01 `Literal` types for frequency/day/severity, time validation; severity derived server-side — `api/routes.py`, `Runbook.jsx`, `EngineerDetail.jsx` — S
- [x] ARCH-02 Scheduling: remove unsupported frequencies or implement them, store a timezone, pick one deployed mechanism (Render Cron Job / GH Actions cron calling the authenticated endpoint, or APScheduler in lifespan), store `last_run_at` in the DB for idempotency — `data/clock.py`, `api/`, `render.yaml`, `Dashboard.jsx` — M
  - *Decision (2026-10-03, developer):* GitHub Actions cron → `POST /api/scheduled-tick`. Biweekly/Monthly removed (VAL-01).
- [x] PERF-02 Single SMTP connection per dispatch, Slack timeout, `BackgroundTasks` + `dispatch_runs` table with status the UI polls — `notifications/*`, `data/alert_worker.py`, `api/routes.py`, `schema.sql` — M
- [x] ERR-02 `config.py` for paths; connections closed (`contextlib.closing`); templates loaded relative to package — `core/db.py`, `notifications/email_report.py`, `data/*.py` — S
- [x] BUG-07 Real 7-day score delta from the API replaces hardcoded arrows and random bars — `api/routes.py`, `Dashboard.jsx` — S
- [x] SEC-02 Jinja `autoescape` — `notifications/email_report.py` — S
- [x] DX-01 Seed on container start if the DB is empty, named volume in compose, document Render reset behavior — `Dockerfile.backend`, `docker-compose.yml` — S
Acceptance criteria:
- With a fixed seed, the same engineers sit in the bottom 2 on ≥ 70% of days (persona stability). Report the measured value.
  - *Result:* 0.71 averaged over seeds 1–5 (test threshold 0.55, every seed > 0.27); 30-seed median 0.65. The shortfall vs 0.70 on some seeds traces to the scoring formula (see ML-03), not the simulator.
- The `/trends` last date equals `MAX(date)` (test).
- Running `seed.py --reset` twice → 10 engineers (test).
- On a fresh `git archive` copy: `python data/seed.py && python main.py` succeeds (with Gemini mocked or the key unset).
- Invalid settings → 422 (test). Unknown severity → 422.
- Trigger endpoint returns in < 500 ms and dispatch status is queryable (test with mocked SMTP).
- Scheduler idempotency test: two ticks in the same window → one dispatch.
Verification commands:
- `pytest -q`
- `git archive HEAD | tar -x -C /tmp/dt && cd /tmp/dt && python data/seed.py --reset && python main.py`
- `docker compose up --build` (manual)
Interview payoff:
- “The leaderboard was random noise; I modeled engineers as personas so ranks mean something, and I can show the stability metric.”
- “Dispatch is idempotent per schedule window, so a retry can’t double-email.”
Risk / rollback:
- The persona generator changes all demo numbers, so screenshots must be retaken in Phase 7. The scheduler choice affects deployment; keep the old `clock.py` until the new mechanism is verified.

## Phase 3 — Testing & CI
Goal: Every push runs lint and tests for both halves; critical paths have meaningful assertions.
Why this order: Comes after the behavior-changing fixes so CI locks in correct behavior rather than the bugs.
Items:
- [x] TEST-01a Tests for `alert_worker` (severity tiers at team sizes 3, 7, 10), notifications with mocked `smtplib`/`urlopen`, and runbook caching — `tests/` — M
- [x] TEST-01b Frontend tests: Dashboard renders API data with mocked fetch, plus error state; Runbook error state — `frontend/src/__tests__/` — M
- [x] TEST-01c GitHub Actions: `ruff check`, `pytest --cov`, `npm ci && npm run lint && npm test && npm run build` — `.github/workflows/ci.yml` — S
- [x] OPS-01 Off switches for GitHub Actions (requested by the developer, 2026-10-03: "turn the GitHub Actions off") — S
  - **Built-in buttons, no code (documented, work today):** per workflow, Actions tab → pick the workflow → `...` → **Disable workflow** (and **Enable workflow** to undo). For the whole repository, Settings → Actions → General → Actions permissions → **Disable actions**. A disabled workflow runs nothing at all, including manual runs.
  - **Repository-variable switches (what gets built):** Settings → Secrets and variables → Actions → **Variables**: `CI_ENABLED` and `SCHEDULED_ALERTS_ENABLED`. Every job in `ci.yml` / `scheduled-alerts.yml` gets `if: vars.<NAME> != 'false' || github.event_name == 'workflow_dispatch'`. Setting a variable to `false` turns off the automatic runs (push / PR / schedule; they show as *skipped*), while **Run workflow** still works for a deliberate manual run. Unset = ON, so nothing changes until you choose. Advantage over the built-in button: the off state is visible in each run, and manual runs keep working.
  - **Command line, same switches:** `gh workflow disable "CI"` / `gh workflow enable "CI"`; `gh variable set SCHEDULED_ALERTS_ENABLED --body false` / `gh variable delete SCHEDULED_ALERTS_ENABLED`.
  - **Guard test:** a pytest parses every file in `.github/workflows/` and fails if any job lacks its kill-switch `if:`, so a job added later can't silently ignore the switch.
  - **Docs:** a README section "Turning GitHub Actions off" (the three methods and what each one stops), plus a short header comment in both workflow files.
  - Not doing: a dashboard button that calls GitHub's API to disable workflows. See "Upgrades I'm Deliberately NOT Recommending".
Acceptance criteria:
- CI is green on push. Backend coverage ≥ 80% on `core/` and `api/` (critical paths, not a vanity number). ESLint 0 errors.
  - *Result:* every CI step reproduced locally on clean environments (Python 3.10 and 3.14 from pinned requirements: 192 passed, 96.4% coverage; clean `npm ci`: ESLint 0, 23 tests, build OK). The first run on github.com happens on the first push of this branch.
- OPS-01: the workflow guard test passes (every job in every workflow carries its kill-switch `if:`), and fails if the `if:` is removed from a job (red→green).
- OPS-01 (manual, on GitHub): with `CI_ENABLED=false` a push shows the CI jobs as *skipped*; with `SCHEDULED_ALERTS_ENABLED=false` the 15-minute runs are *skipped* but **Run workflow** still executes; deleting the variables restores both.
Verification commands:
- `pytest --cov=core --cov=api --cov=ai --cov-report=term-missing`
- `npm --prefix frontend run lint && npm --prefix frontend test`
- OPS-01 manual: set/unset the two variables (Settings or `gh variable set ...`), push a commit, and click Run workflow; then try Actions → CI → `...` → Disable workflow / Enable workflow.
Interview payoff:
- A CI badge, plus “external services are mocked at the boundary, so tests are deterministic and free”.
- OPS-01: “Every workflow has an off switch that doesn't need a code change: a repository variable checked by each job, so automatic runs stop but a deliberate manual run still works. A test makes sure no job is ever added without it, and GitHub's own Disable button stays available as the hard stop.”
Risk / rollback:
- None to runtime.

## Phase 4 — Architecture & Code Quality
Goal: One source of truth per concept; remove what doesn’t exist; make the score defensible.
Why this order: Refactoring is safe only once Phase 3 tests exist.
Items:
- [x] ARCH-01 `core/severity.py` (single tier rule used by API, worker, and CLI); `core/queries.py`; delete empty `models.py`/`leaderboard.py` or implement them; delete `get_daily_records`; prompts move to `ai/prompts.py` — M
  - *Partly done in Phase 2:* `core/severity.py` (commit aa8479b) and `core/queries.py` (BUG-04) exist and are used by the API, worker and CLI. Remaining: empty `models.py`/`leaderboard.py`, prompts into `ai/prompts.py`, other duplicated queries.
- [x] ML-03 Cache ratio on total prompt tokens (verify Anthropic semantics first), mix normalized/capped, sub-score breakdown returned by the API, rationale + limitations in `docs/scoring.md` — `core/scorer.py`, `api/routes.py` — S–M
  - *Decisions (2026-10-03, developer):* token fields match Anthropic's `usage` semantics (with a data migration); the `/compact` term is pooled over 7 days. Result: bottom-2 stability median 0.65 → 0.82 over 30 seeds; property tests in place.
  - *New input from ML-02:* the `compacts / sessions` term causes almost all daily rank noise (within-engineer daily SD 7.1 pts vs 1.6 cache, 0.7 mix). Score it over a rolling window (pooled compacts / pooled sessions over 7 days) or shrink it toward the engineer's mean; re-measure bottom-2 stability (Phase 2: 5-seed mean 0.71, 30-seed median 0.65).
- [x] Hygiene bundle: unused imports, `logging` instead of print, bare excepts, stray files (`test.txt`, `api/guide.txt`, Vite README) — S
  - *Partly done in Phase 3:* unused imports (ruff + ESLint now 0, enforced by CI), the swallowed team-report error, bare excepts in the SMTP code (PERF-02). Remaining: `logging` instead of print, stray files (`test.txt`, `api/guide.txt`, Vite README).
- [x] SEC-03 / DX-02 `npm audit fix` + re-test; pinned Python deps; one stated Python version (3.12 recommended) in README, Dockerfile, CI — S
  - *Result:* npm audit 0 (shipped and dev), pip-audit clean; Python 3.13 chosen over 3.12 (support until Oct 2029).
Acceptance criteria:
- `grep -rn '"critical"' --include=*.py` shows tier logic only in `core/severity.py`.
  - *Result:* tier **decisions** live only in `core/severity.py`; other matches only consume the tier (email colours, Slack emoji, prompt tone, validation). The email template's hidden `rank <= 5` copy was found by this check and removed.
- Score tests updated, including property tests (score ∈ [0, 100]; monotonic non-decreasing in cache ratio).
- `npm audit --omit=dev` shows 0 high.
Verification commands:
- `ruff check . && pytest -q && npm --prefix frontend audit --omit=dev`
Interview payoff:
- “The severity rule existed in four places with two different definitions; I consolidated it and the tests proved nothing changed.”
Risk / rollback:
- ML-03 changes scores, which is intended. Note before/after distributions in FIX_LOG.

## Phase 6 — Interview Upgrades

- [x] **UPG-01 Grounded, structured, persisted AI coaching + eval harness** (flagship) — *v1 → v2 on gemini-3.5-flash-lite, 30 profiles: targeting 50% → 100%, guides with no ungrounded number 80% → 100%. Deviations: guides are stored in a new `coaching_guides` table (`ai_guides` dropped when empty); the action schema uses `focus` instead of `metric_cited`/`est_saving`, because a model-estimated saving would be an ungrounded number by construction; the main model falls back to Flash-Lite on quota or overload.*
  - Problem it solves in THIS project: LLM output is parsed by line heuristics (LLM-01), failures are cached (BUG-02), nothing is persisted (`ai_guides` unused), and nobody knows whether the advice cites the engineer’s real numbers, which the prompt asks for.
  - What gets built (scope-limited):
    - Gemini `response_schema` / JSON mode that returns `{headline, actions:[{title, problem, fix, metric_cited, est_saving}]}`, validated by Pydantic, with one repair retry that feeds the validation error back.
    - Timeout plus exponential backoff on 429/5xx, and a rule-based fallback generated from sub-scores (not a static list).
    - Persisted in `ai_guides`, keyed `(user_id, date, prompt_version, model)`.
    - A provider interface (`GuideProvider`) so the README’s Claude-swap claim becomes true, with the Claude implementation optional.
    - `evals/`: 30 fixed engineer profiles spanning the persona space, plus automated checks: schema-valid rate, **grounding rate** (every number cited appears in the input within rounding), **targeting rate** (the first action addresses the weakest sub-score), and length. A script prints a table per prompt_version/model.
  - Evidence it produces: an eval table such as “prompt v1: valid <x>%, grounded <y>%, targeted <z>% → v2: …”, plus a parse-failure rate before and after structured output.
  - Talking point: “I treated the coaching guide as a product with a spec: structured output, a grounding check that catches hallucinated numbers, and an eval set I re-run whenever I change the prompt or model.”
  - Follow-ups the interviewer will ask + what you must understand:
    - Why rule-based checks instead of LLM-as-judge? (Cheap, deterministic, and grounding is checkable; know where a judge *would* be needed, e.g. tone.)
    - What happens when the repair retry also fails? (Rule-based fallback, marked as such, not cached as success.)
    - How do you version prompts? How do you avoid sending PII? (Only metrics, never email.)
    - Eval-set overfitting.
    - Cost per guide (ties to UPG-04).
  - Effort: L | Interview impact: 5 | Buzzword risk: Low (it produces numbers)

- [x] **UPG-02 Telemetry ingestion API + real cost model** (flagship, SDE) — *10k records in 0.66 s on SQLite; the simulator shares the code path.*
  - Problem it solves in THIS project: Data only comes from a generator writing directly to SQLite. Cost is random (ML-01). The README promises tracking real usage but there is no input contract.
  - What gets built (scope-limited):
    - `POST /api/ingest` (admin-token protected) that accepts a batch of per-engineer daily usage records, modeled on the fields Claude Code’s OpenTelemetry token/cost metrics or Anthropic’s usage report expose. **Verify the current field names in the docs before designing the schema, and say “modeled on”, not “compatible with”, unless you test it.**
    - Pydantic validation (non-negative tokens, mix sums ≈ 1, date not in the future), server-side cost via `core/pricing.py` (client cost ignored), score computed on write.
    - Idempotent upsert on `(user_id, date)` (`INSERT … ON CONFLICT DO UPDATE`), with a response that reports inserted/updated/rejected counts with reasons.
    - The persona simulator posts through this endpoint (or the same service function), so synthetic and real data share one path.
  - Evidence it produces: tests proving re-sending a batch creates no duplicates; a rejected-record report for malformed input; ingest throughput for e.g. 10k records (measure it; don’t guess).
  - Talking point: “The simulator is just one producer. Everything, real or synthetic, goes through one validated, idempotent ingestion contract, and cost is computed server-side from a dated price table.”
  - Follow-ups the interviewer will ask + what you must understand:
    - Why upsert instead of insert? (Retries and late corrections.)
    - Why compute cost server-side?
    - Price changes over time: store `price_version` per row.
    - What changes at 1,000 engineers? (SQLite single writer; when Postgres becomes worth it.)
    - Timezones of “date”.
    - How a real producer would authenticate.
  - Effort: M–L | Interview impact: 4 | Buzzword risk: Low

- [x] **UPG-03 Explainable score + sensitivity check** — *Kendall τ 0.93–0.98 under ±20%; bottom 2 unchanged in 83–93% of teams.*
  - Problem it solves in THIS project: The score is a black box in the UI, and its weights (40/30/30, Haiku = 1.0) are arbitrary (ML-03).
  - What gets built: API returns sub-scores; EngineerDetail shows the breakdown; `docs/scoring.md` explains the rationale; a small script perturbs each weight ±20% and reports rank stability (Kendall τ vs baseline) on the simulated team.
  - Evidence it produces: “rankings have Kendall τ ≥ <x> under ±20% weight changes”, i.e. whether conclusions are robust to the arbitrary choices.
  - Talking point: “The weights are a judgment call, so I measured how much the leaderboard depends on them.”
  - Follow-ups the interviewer will ask + what you must understand: what Kendall τ measures; why not learn the weights (no ground-truth label of ‘efficient’); Goodhart’s law (engineers gaming `/compact`).
  - Effort: S–M | Interview impact: 3 | Buzzword risk: Low

- [x] **UPG-04 LLM cost & latency tracking for the app’s own AI calls** — *`ai_requests` table + `GET /api/ai-stats`.*
  - Problem it solves in THIS project: A token-efficiency tool that doesn’t measure its own token spend. There is no visibility into Gemini latency or failures.
  - What gets built: Record `usage_metadata` tokens, latency in ms, model, prompt_version, and outcome (ok/repaired/fallback) per generation in `ai_guides` (or an `llm_calls` table); a small `/api/ai-stats` endpoint; cache hit rate.
  - Evidence it produces: p50/p95 generation latency, tokens and $ per guide, cache hit rate, fallback rate.
  - Talking point: “I dogfooded the product’s idea: every LLM call the app makes is metered, so I know a guide costs <$x> and p95 is <y> s.”
  - Follow-ups the interviewer will ask + what you must understand: where the token counts come from (provider usage metadata, not estimates); percentile vs average.
  - Effort: S | Interview impact: 3 | Buzzword risk: Low

Acceptance criteria (phase):
- `python -m evals.run` prints the table and the numbers are recorded in README/FIX_LOG.
- Ingest idempotency and rejection tests pass.
- All metrics in resume bullets come from these outputs.
Verification commands:
- `pytest -q && python -m evals.run --pipeline v2` (replay; add `--mode live` only with approval)
Risk / rollback:
- UPG-01 depends on Gemini structured-output support for the pinned SDK version, so check the SDK docs first. Run evals against recorded responses in CI and live only manually (cost and rate limits).

## Phase 7 — Ship & Document
Goal: The repo, README, and live demo tell the same true story.
Why this order: Last, because it documents what was actually built and measured.
Items:
- [x] DOC-01 Rewrite README from the code: accurate stack, real `main.py` output, scoring rationale link, architecture diagram (Mermaid), “Known limitations” section, measured numbers only; delete references to missing files or add `LICENSE` — S
- [~] Redeploy; `/health` endpoint; verify the Runbook works on the live URL; retake screenshots — S — *`/health` + render.yaml done, screenshots retaken (after UI-01); the live deploy waits for the PR merge and the `deployment` branch update*
- [ ] Re-run the `project-interview-report` skill, then `project-mock-interview` — S — *developer will do this later*
### Phase 7 prep (2026-10-04, gathered while the Phase 6 eval ran)

**README claim audit (current README → fix):**

| README says | Reality | Fix |
|---|---|---|
| `python main.py` output dated 2024 with "Waste Pattern" column, "✓ Sending manager report via email" | Invented. `main.py` prints a leaderboard, a team report and guides for the bottom 5; it sends no email (dispatch is `POST /api/trigger-alerts`) | Paste real output from a temp-DB run (~6 Gemini calls, Flash-Lite fallback covers quota) |
| Sample guide with "saves ~85%", "6× the team average", "Estimated saving: 50–70%" | Invented numbers; v2 deliberately has no model-estimated savings | Paste a real v2 guide from `evals/recordings/` |
| "$150–250 per developer per month", "top 10% spend 2–3×" | No source in repo | Use the sourced figure already in the code/docs: ~$13/developer/active day, 90% under $30 (Anthropic) |
| Architecture: ASCII box, "Daily Agent" at the centre | Real flow: producers → `POST /api/ingest` → SQLite → API → React; scheduler = GitHub Actions tick; LLM via `GuideProvider` with Flash-Lite fallback | Mermaid diagram |
| Scoring table: "Weighted penalty for Opus on simple tasks", targets ≥60% / ≤20% Opus | Model mix ignores task difficulty; no targets in code | Short summary + link to docs/scoring.md (breakdown, 7-day pooling, sensitivity) |
| Project tree: `core/models.py`, `core/leaderboard.py`, `frontend/index.html`, Chart.js, `api/main.py` only | Those files don't exist; frontend is React 19 + Vite + Recharts + Tailwind | Regenerate the tree from `git ls-files` |
| Badges: FastAPI 0.104, License MIT | FastAPI 0.136.3; **no LICENSE file** | Fix badge; add LICENSE (needs your choice) or drop the badge |
| Getting started: `python data/seed.py`, `uvicorn api.main:app` → "Open http://localhost:8000" | Dashboard is the Vite app (`cd frontend && npm ci && npm run dev`, :5173); :8000 is the API | Two-terminal quick start + `docker compose up` path; verify on a fresh clone |
| Roadmap: "FastAPI dashboard with Chart.js" | Recharts | Rebuild roadmap from FIX_LOG |
| (missing) | Evals, ingestion, metering, CI + off switches, admin token, known limitations | New sections, measured numbers only |

**Measured numbers available (source):**
- Tests: 297 backend, 26 frontend; coverage 97% of 1,267 statements (pytest-cov, 2026-10-04; CI gate ≥ 85%).
- Ingestion: 10,000 records in 0.66 s on SQLite (FIX_LOG UPG-02).
- Leaderboard latency while a guide waits 1.5 s on the LLM: 1.32 s → 0.016 s (FIX_LOG CONC-01).
- Alert dispatch: `POST /api/trigger-alerts` answers 202 in 41 ms (FIX_LOG PERF-02).
- Score: bottom-2 stability 65% → 82%; weight sensitivity τ 0.93–0.98 (docs/scoring.md).
- Evals (gemini-3.5-flash-lite, 30 profiles): targeting 50% → 100%, guides with no ungrounded number 80% → 100%, ~$0.0009 per guide (FIX_LOG UPG-01).
- Dependencies: npm audit 0, pip-audit clean (FIX_LOG SEC-03).

**Deploy checklist:**
- [x] Add `GET /health` (DB reachable, schema version; no secrets) + test; set `healthCheckPath: /health` in render.yaml.
- [x] render.yaml: frontend service has no `VITE_API_URL` (it's baked in at build time, so a missing value means the dashboard calls 127.0.0.1); add it, plus `GEMINI_FALLBACK_MODEL` documentation on the backend.
- [ ] Get the branch onto GitHub: 68 commits on `phase-6-upgrades` are not pushed; `main` is at dc60f00. Merge via PR so CI runs on GitHub first.
- [ ] Render: confirm which branch it deploys (`main` or `deployment`), set `ADMIN_TOKEN`, `FRONTEND_URL`, `GEMINI_API_KEY`; repository secrets `DEVTELEMETRY_API_URL` / `DEVTELEMETRY_ADMIN_TOKEN` for the scheduled tick (or leave `SCHEDULED_ALERTS_ENABLED=false`).
- [ ] Verify live: `/health`, leaderboard, engineer page breakdown, Runbook guide (BUG-01 check in DevTools: no request to 127.0.0.1).
- [x] Retake the 3 screenshots + one of the score breakdown.
- [x] Fresh `git clone` into a temp dir and follow the README verbatim (< 10 min). — *~4 min*

**Repo hygiene before the rewrite:** `DEVTELEMETRY_INTERVIEW_REPORT.md`, `interview_study_guide.md` and `demo_commands.txt` are **tracked**, so they are public on GitHub once pushed: personal interview prep, not project docs. Decide: delete from the repo (keep locally, gitignore) or move under `docs/`. (`engineers_data.json` is already gitignored.)

**Decisions (developer, 2026-10-04):**
- **Licence: none.** Remove the MIT badge and the LICENSE link (default copyright applies).
- **Push: push `phase-6-upgrades` and open a PR into `main`**; CI runs on GitHub, and the developer reviews and merges.
- **Render deploys the `deployment` branch.** After the merge, `deployment` must be updated to the merged `main` for the live demo to change, so `/health` and the render.yaml fixes ship that way.
- **Notes files: untrack, keep locally** (gitignore).
  - `interview_study_guide.md` and `demo_commands.txt` are already on `origin/main` (dc60f00), so they stay in old history.
  - `DEVTELEMETRY_INTERVIEW_REPORT.md` was added in unpushed b133b29. Pushing would publish it in history unless the unpushed commits are rewritten without it. **Ask before pushing:** rewrite (backup branch first) or accept.

Acceptance criteria:
- Every README claim maps to code or a measured output. A fresh clone works by following the README in < 10 minutes.
Verification commands:
- Fresh `git clone` into a temp dir and follow the README verbatim.
Interview payoff:
- A recruiter-clickable demo that holds up when an engineer opens the code.
Risk / rollback:
- Render free-tier cold start. Mention it upfront when demoing.

---

## Phase 8 — Measured Features (planned 2026-10-04)

**Goal:** four features that widen the project's scope, each ending in a *measured* claim the way the Phase 6 evals do.

**Why these:**
- **Real telemetry is out of scope.** There is no access to real office usage, and the developer's own usage wouldn't represent one, so the real-telemetry connector was rejected.
- **Each feature has an honest measurement:**
  - *8a:* a simulated ground truth to check a causal estimate against;
  - *8b:* exact re-pricing;
  - *8c:* injected incidents with known positions;
  - *8d:* an eval set.

**Order:** 8a → 8b → 8c → 8d. 8a creates `coaching_events`, which the dashboard uses; 8d uses 8c's anomaly count. Each can ship on its own.

**Ground rules (same as Phases 0–7):**
- **Branch and commits:** branch `phase-8-features`; red→green tests; one commit per item; a FIX_LOG entry per item.
- **Approvals:** push and PR only with approval, and **never push `deployment`** (Render auto-deploys it). Each live Gemini eval run needs approval and uses `--model gemini-3.5-flash-lite` (free-tier quota).
- **Reuse:**
  - `core/scorer.score_breakdown` / `score_history`;
  - `core/pricing.estimate_cost`;
  - `ai/features.coaching_facts`;
  - `core/ingest.upsert_usage`;
  - the in-memory simulation pattern in `analysis/weight_sensitivity.py`;
  - the `evals/` harness (`--profiles`, `--only-missing`, recordings).

Items:

- [x] **UPG-05 Did the coaching work? Measuring impact without fooling yourself** (flagship)
  - *Done 2026-10-07:* DiD +0.02 under no effect (98% coverage) and +4.13 vs a true +4.13; naive +0.82 and "it worked" in 18% of no-effect teams. Baseline changed from the planned −14..−1 to −13..−7 (the selection day pools `/compact` over −6..0); see FIX_LOG and docs/impact.md.
  - **Problem it solves in THIS project:**
    - The app sends guides but never checks whether anyone improved.
    - The engineers who get the critical runbook are the **bottom 2 by that day's score** (`data/alert_worker.py`, `core/severity.py`). Selecting on a low score guarantees regression to the mean, so a naive before/after shows improvement even when coaching does nothing.
    - Nothing records who was coached, and simulated personas never change habits, so there is no ground truth to validate a method against.
  - **What gets built:**
    - **`coaching_events` table** (`data/schema.sql`): `user_id`, `coached_on`, `severity`, `target_area`, `source` (`dispatch` | `simulated`), `UNIQUE(user_id, coached_on)`. `data/alert_worker.py` inserts a row for each **critical** engineer whose alert was actually `sent`; the target area is `coaching_facts(...)["weakest_area"]`.
    - **Simulated truth** (`data/seed.py`):
      - A weekly coaching day coaches the bottom 2.
      - The coached persona's habit for the target area improves by a configurable true effect (`cache_hit` +Δ, `opus_share` −Δ moved to Sonnet, `compact_rate` +Δ), with an adherence probability.
      - `--coaching-effect none|small|moderate` (default `moderate` for the demo) writes `source='simulated'` events.
      - The simulator stays deterministic. Re-check the persona-stability test and record any threshold change with its measured value.
    - **Estimators** (`core/impact.py`, pure functions; the outcome is points in the targeted area from `score_breakdown`):
      - *naive:* mean of days +1..+7 minus the coaching-day value. Kept to show the bias.
      - *difference-in-differences:* (coached: mean of +1..+7 minus mean of −14..−1, **excluding the selection day**) minus (the same for uncoached engineers in the same calendar windows, which cancels the weekday mix and team trends).
      - A 95% bootstrap CI over events, with a fixed seed.
    - **Validation** (`analysis/coaching_impact.py`): ~200 simulated teams × true effect ∈ {0, moderate}. It reports each method's mean estimate, bias, CI coverage, and the "coaching works" false-positive rate under no effect, written up in `docs/impact.md`.
    - **Product:**
      - `GET /api/coaching-impact?days=` returns per-event before/after plus `{did, ci_low, ci_high, n_events, naive}`.
      - Dashboard "Coaching impact" card: the estimate ± CI, with the naive number labelled "naive before/after (biased by regression to the mean)".
      - Coaching-day markers on the engineer trend chart.
  - **Evidence it produces:** a table showing that with **no** true effect the naive method claims improvement, while difference-in-differences stays ≈ 0 with ~95% coverage, and that it recovers a known effect.
  - **Talking point:** "The obvious metric said coaching worked even when I'd set the true effect to zero. It was regression to the mean, because we coach whoever had the worst day. I fixed the method, and proved it on a simulation where I knew the right answer."
  - **Follow-ups the interviewer will ask + what you must understand:**
    - What regression to the mean is, and why selecting on a low score causes it.
    - The parallel-trends assumption.
    - Why exclude the selection day from the baseline.
    - Why not just randomize (ethics/practicality; a random holdout is the gold standard).
    - Bootstrap CIs.
    - What would change with real data.
  - **Effort:** M–L (~2–3 sessions) | **Interview impact:** 5 | **Buzzword risk:** Low (it produces numbers)

- [ ] **UPG-06 What-if savings calculator** (grounded savings in the guides)
  - **Problem it solves in THIS project:** engineers see a score, not money. The Phase 6 guide schema dropped `est_saving` because a model-estimated saving is an ungrounded number by construction.
  - **What gets built:**
    - **Re-pricing** (`core/whatif.py`): re-prices an engineer's last 30 days of actual tokens with `estimate_cost` under target levers:
      - *cache:* the same prompt tokens re-split between `input` and `cache_read` at the target hit ratio, cache writes unchanged;
      - *model:* a target Opus share, moved to Sonnet.

      It returns current vs projected monthly cost and the saving per lever and combined. Inputs are validated (cache hit ≤ 0.97; shares in [0, 1]).
    - **Data-driven defaults:** the team's top-quartile cache hit and Opus share, not invented targets.
    - **API and UI:** `GET /api/engineer/{id}/what-if?cache_hit=&opus_pct=` (invalid values → 422), and a debounced sliders panel on `EngineerDetail.jsx`.
    - **Guides cite real savings:** add computed savings (e.g. `saving_month_usd_cache_to_team_p75`) to `coaching_facts`. Prompt **v3** may cite them, and they're grounded because code computed them. Add a golden prompt test.
  - **Evidence it produces:**
    - property tests: a higher cache hit never costs more; less Opus never costs more; no change gives the identical cost;
    - a **live v2 vs v3 eval on Flash-Lite, 30 profiles (needs approval)** with no regression in validity, targeting or grounding.
  - **Talking point:** "The model isn't allowed to estimate savings, because it would make them up. The code re-prices the engineer's real tokens under a target habit, and the guide quotes that number."
  - **Effort:** S–M (~1–2 sessions) | **Interview impact:** 4 | **Buzzword risk:** Low

- [ ] **UPG-07 Cost anomaly detection, measured on injected incidents**
  - **Problem it solves in THIS project:** a runaway agent loop or broken caching shows up only as a bigger bill. The roadmap's "budget alerts" were never built.
  - **What gets built:**
    - **Detector** (`core/anomaly.py`):
      - A per-engineer robust baseline: the median and MAD of daily cost over the previous 28 days **of the same day type** (weekday vs weekend, so weekend dips aren't flagged). At least 8 baseline days, otherwise not evaluated.
      - Flag when robust z = 0.6745·(x − median)/MAD ≥ 3.5 **and** x − median ≥ a $ floor.
      - Name the driver: uncached input (caching broke), Opus share, or output volume.
    - **Evaluation** (`analysis/anomaly_eval.py`): injects known incidents into simulated teams (runaway-loop days with tokens ×3–6; cache-breakage days with hit ~10%). Over ~200 simulations it reports precision, recall and false alarms per engineer-month for three detectors (robust, a fixed `$30/day` threshold, mean ± 3σ), written up in `docs/anomalies.md`.
    - **Product:**
      - `GET /api/anomalies?days=14`;
      - a dashboard "Spend anomalies" list, and anomaly days marked on the engineer page;
      - a line in the manager digest;
      - seed `--incidents` for the demo. Detection never reads the injection.
  - **Evidence it produces:** the robust detector beats both baselines on F1 with ≤ 1 false alarm per engineer-month.
  - **Talking point:** "A fixed threshold either misses a light user's runaway loop or pages a heavy user every Monday. Comparing each person to their own normal, with weekends separate, caught N% of injected incidents at under one false alarm a month."
  - **Follow-ups:**
    - Why median/MAD instead of mean/σ (outliers inflate σ).
    - Seasonality (the weekday/weekend split).
    - Choosing the threshold (the precision/recall trade-off).
    - The cold start.
  - **Effort:** S–M (~1–2 sessions) | **Interview impact:** 4 | **Buzzword risk:** Low

- [ ] **UPG-08 Grounded team memo**
  - **Problem it solves in THIS project:** the manager's team memo still uses a free-text prompt with no grounding check. In Phase 7 testing it recommended a Claude Code feature that doesn't exist (`.claudedir`); this is a documented README limitation.
  - **What gets built:**
    - **Pipeline:** a `TeamMemo` schema (`ai/schemas.py`: summary plus 1–2 focus areas with `Literal` areas) and team facts: team size, average score, total cost, team-wide points lost per area, critical count, anomaly count (UPG-07). The structured `team-v2` prompt replaces `build_team_report_prompt`, with the same pipeline as the guides: JSON schema, validation, one repair, a rule-based memo fallback. Metering is already in place.
    - **"Invented feature" guard:** an allowlist of real Claude Code commands (**verify against Claude Code's docs before writing it**). An eval check fails any `/command` outside it.
    - **Evals:** ~15 simulated team-day profiles. Checks: valid, grounded numbers, names the team's biggest area, no unknown commands.
  - **Evidence it produces:** a **live old-vs-new memo eval on Flash-Lite (needs approval)**. Then the README limitation is removed.
  - **Effort:** S (~1 session) | **Interview impact:** 3 | **Buzzword risk:** Low

Acceptance criteria (phase):
- **UPG-05:**
  - with no true effect, naive is clearly > 0 while difference-in-differences is ≈ 0 with 90–98% CI coverage;
  - with the moderate effect, difference-in-differences is within ±10% of the truth.
- **UPG-06:** the savings properties hold; v3 does not regress on any eval metric against v2 (same model, same 30 profiles).
- **UPG-07:** the robust detector beats both baselines on F1 with ≤ 1 false alarm per engineer-month.
- **UPG-08:** the new memo is 100% valid, with no ungrounded numbers and no unknown commands on the eval set.
- **Every phase:**
  - every number in docs, README and FIX_LOG is copied from a script's output;
  - coverage stays ≥ 85%, with the new `core/` modules near 100%.

Verification commands:
- `pytest && ruff check . && npm --prefix frontend test && npm --prefix frontend run lint && npm --prefix frontend run build`. Bare `pytest`, exactly as CI runs it.
- `python -m analysis.coaching_impact`, `python -m analysis.anomaly_eval`
- `python -m evals.run --pipeline v3 --mode live --model gemini-3.5-flash-lite` (approval), then replay in CI.
- A fresh clone + `docker compose up --build` + a browser check (Playwright + Edge) of the new panels; retake the screenshots.

Risk / rollback:
- **Simulation risk (UPG-05):** the coaching effect changes the simulated data. Personas, eval profiles and the published eval recordings must not change. `evals/profiles.json` is generated independently; confirm that the committed eval tables still reproduce.
- **Prompt change (UPG-06):** prompt v3 changes the stored guide key (`prompt_version`), so existing guides regenerate once.
- **Deploy:** only on the developer's explicit go-ahead.

---

## Upgrades I’m Deliberately NOT Recommending

| Idea | Why not for this project |
|---|---|
| Dashboard button that turns GitHub Actions on/off via the GitHub API | The backend would need a GitHub token with write access to the repo's Actions: a much bigger blast radius if the server or its env leaked, for a switch GitHub already provides as a button (Actions tab) and a repository variable. |
| Kubernetes / microservices | One API, 10 synthetic engineers, one worker. There is no scaling or team-boundary problem to point to. |
| Celery + Redis job queue | Dispatch is ~11 messages per week. `BackgroundTasks` + a `dispatch_runs` table gives status and idempotency without new infrastructure. Mention a queue as the next step if dispatch volume grows. |
| Migrate to PostgreSQL now | SQLite is fine for a single instance at this size. The real deployment problem is the ephemeral disk, which a Render disk or an honest “resets on restart” note solves. Explain when Postgres becomes worth it (multiple instances, concurrent writers) instead of doing it. |
| Vector DB / RAG over “best practices” docs | The advice space is about five well-known habits; retrieval adds a component without a retrieval problem. |
| Fine-tuning a model for guides | No labeled data and no eval baseline. UPG-01’s eval harness is the prerequisite, and prompting will likely suffice. |
| Training an ML model to “predict efficiency” | There’s no ground-truth label and the data is synthetic, so you’d learn your own generator. That’s easy to expose in an interview. |
| LangChain / an agent framework | A single prompt → structured output call doesn’t need an agent loop. A framework hides the parts you need to explain. |
| Full OAuth/RBAC with user accounts | There are no real users. An admin token on mutating routes is proportionate; be ready to describe what real multi-tenant auth would look like. |
| WebSockets / “real-time” dashboard | Data changes daily. Polling or plain reloads are correct. |
| Slack bot (`/myusage` command) from the roadmap | Another external surface to secure and test, with little added signal. Do it only after Phase 7 if time remains. |

## Resume Bullets (write only AFTER the phase is done — templates)

Fill placeholders only with numbers printed by your own scripts or tests. Never guess.

- Built DevTelemetry, a FastAPI + React platform that scores AI-coding-tool token efficiency across <N> engineers from <ingested/simulated> usage and generates personalized coaching via an LLM. Live demo: <url>.
- Designed an idempotent, schema-validated telemetry ingestion API with server-side cost computation from a versioned model price table; handled <N> records with <0> duplicates under retry (<test name>).
- Made LLM coaching reliable with structured output, schema validation, repair retry, and a rule-based fallback; built a <30>-profile eval harness that raised grounding rate from <x>% to <y>% across prompt versions.
- Diagnosed an event-loop blocking bug where one LLM request raised dashboard latency from <0.01 s> to <2.8 s>; fixed it and added a concurrency regression test.
- Instrumented the app’s own LLM usage (tokens, $ per guide, p95 latency <y> s, cache hit rate <z>%).
- Set up CI (pytest, Vitest, ESLint, ruff) with <n> tests and <x>% coverage on core scoring and API code.
