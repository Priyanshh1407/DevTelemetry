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
| 3 | Testing & CI | TEST-01 completion, GitHub Actions, coverage on core | ~1.5 days | Green badge, mocked external services |
| 4 | Architecture cleanup | ARCH-01, ML-03, lint/hygiene, SEC-03, DX-02 | ~2 days | Single source of truth for severity and queries |
| 6 | Interview upgrades | UPG-01, UPG-02, UPG-03, UPG-04 | ~5–7 days | Eval numbers, ingestion contract, LLM cost tracking |
| 7 | Ship & document | README rewrite, diagram, deploy, re-run interview report | ~1.5 days | Honest, clickable demo |

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
- [ ] BUG-05 Trends and history return the latest 30 days (test with 40 days of data) — `api/routes.py` — S
- [ ] BUG-06 `seed.py --reset`, fixed RNG seed, deterministic engineer IDs — `data/seed.py` — S
- [ ] ML-02 Persona-based synthetic generator (latent habits + noise + weekday effect), documented assumptions — `data/seed.py` (or `data/simulator.py`) — M
- [ ] BUG-04 `main.py` reads from the DB via shared queries; delete the JSON path and `scorer.generate_mock_data` — `main.py`, `core/scorer.py` — M
- [ ] VAL-01 `Literal` types for frequency/day/severity, time validation; severity derived server-side — `api/routes.py`, `Runbook.jsx`, `EngineerDetail.jsx` — S
- [ ] ARCH-02 Scheduling: remove unsupported frequencies or implement them, store a timezone, pick one deployed mechanism (Render Cron Job / GH Actions cron calling the authenticated endpoint, or APScheduler in lifespan), store `last_run_at` in the DB for idempotency — `data/clock.py`, `api/`, `render.yaml`, `Dashboard.jsx` — M
- [ ] PERF-02 Single SMTP connection per dispatch, Slack timeout, `BackgroundTasks` + `dispatch_runs` table with status the UI polls — `notifications/*`, `data/alert_worker.py`, `api/routes.py`, `schema.sql` — M
- [ ] ERR-02 `config.py` for paths; connections closed (`contextlib.closing`); templates loaded relative to package — `core/db.py`, `notifications/email_report.py`, `data/*.py` — S
- [ ] BUG-07 Real 7-day score delta from the API replaces hardcoded arrows and random bars — `api/routes.py`, `Dashboard.jsx` — S
- [ ] SEC-02 Jinja `autoescape` — `notifications/email_report.py` — S
- [ ] DX-01 Seed on container start if the DB is empty, named volume in compose, document Render reset behavior — `Dockerfile.backend`, `docker-compose.yml` — S
Acceptance criteria:
- With a fixed seed, the same engineers sit in the bottom 2 on ≥ 70% of days (persona stability). Report the measured value.
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
- [ ] TEST-01a Tests for `alert_worker` (severity tiers at team sizes 3, 7, 10), notifications with mocked `smtplib`/`urlopen`, and runbook caching — `tests/` — M
- [ ] TEST-01b Frontend tests: Dashboard renders API data with mocked fetch, plus error state; Runbook error state — `frontend/src/__tests__/` — M
- [ ] TEST-01c GitHub Actions: `ruff check`, `pytest --cov`, `npm ci && npm run lint && npm test && npm run build` — `.github/workflows/ci.yml` — S
Acceptance criteria:
- CI is green on push. Backend coverage ≥ 80% on `core/` and `api/` (critical paths, not a vanity number). ESLint 0 errors.
Verification commands:
- `pytest --cov=core --cov=api --cov=ai --cov-report=term-missing`
- `npm --prefix frontend run lint && npm --prefix frontend test`
Interview payoff:
- A CI badge, plus “external services are mocked at the boundary, so tests are deterministic and free”.
Risk / rollback:
- None to runtime.

## Phase 4 — Architecture & Code Quality
Goal: One source of truth per concept; remove what doesn’t exist; make the score defensible.
Why this order: Refactoring is safe only once Phase 3 tests exist.
Items:
- [ ] ARCH-01 `core/severity.py` (single tier rule used by API, worker, and CLI); `core/queries.py`; delete empty `models.py`/`leaderboard.py` or implement them; delete `get_daily_records`; prompts move to `ai/prompts.py` — M
- [ ] ML-03 Cache ratio on total prompt tokens (verify Anthropic semantics first), mix normalized/capped, sub-score breakdown returned by the API, rationale + limitations in `docs/scoring.md` — `core/scorer.py`, `api/routes.py` — S–M
- [ ] Hygiene bundle: unused imports, `logging` instead of print, bare excepts, stray files (`test.txt`, `api/guide.txt`, Vite README) — S
- [ ] SEC-03 / DX-02 `npm audit fix` + re-test; pinned Python deps; one stated Python version (3.12 recommended) in README, Dockerfile, CI — S
Acceptance criteria:
- `grep -rn '"critical"' --include=*.py` shows tier logic only in `core/severity.py`.
- Score tests updated, including property tests (score ∈ [0, 100]; monotonic non-decreasing in cache ratio).
- `npm audit --omit=dev` shows 0 high.
Verification commands:
- `ruff check . && pytest -q && npm --prefix frontend audit --omit=dev`
Interview payoff:
- “The severity rule existed in four places with two different definitions; I consolidated it and the tests proved nothing changed.”
Risk / rollback:
- ML-03 changes scores, which is intended. Note before/after distributions in FIX_LOG.

## Phase 6 — Interview Upgrades

- [ ] **UPG-01 Grounded, structured, persisted AI coaching + eval harness** (flagship)
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

- [ ] **UPG-02 Telemetry ingestion API + real cost model** (flagship, SDE)
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

- [ ] **UPG-03 Explainable score + sensitivity check**
  - Problem it solves in THIS project: The score is a black box in the UI, and its weights (40/30/30, Haiku = 1.0) are arbitrary (ML-03).
  - What gets built: API returns sub-scores; EngineerDetail shows the breakdown; `docs/scoring.md` explains the rationale; a small script perturbs each weight ±20% and reports rank stability (Kendall τ vs baseline) on the simulated team.
  - Evidence it produces: “rankings have Kendall τ ≥ <x> under ±20% weight changes”, i.e. whether conclusions are robust to the arbitrary choices.
  - Talking point: “The weights are a judgment call, so I measured how much the leaderboard depends on them.”
  - Follow-ups the interviewer will ask + what you must understand: what Kendall τ measures; why not learn the weights (no ground-truth label of ‘efficient’); Goodhart’s law (engineers gaming `/compact`).
  - Effort: S–M | Interview impact: 3 | Buzzword risk: Low

- [ ] **UPG-04 LLM cost & latency tracking for the app’s own AI calls**
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
- `pytest -q && python -m evals.run --prompt-version v2`
Risk / rollback:
- UPG-01 depends on Gemini structured-output support for the pinned SDK version, so check the SDK docs first. Run evals against recorded responses in CI and live only manually (cost and rate limits).

## Phase 7 — Ship & Document
Goal: The repo, README, and live demo tell the same true story.
Why this order: Last, because it documents what was actually built and measured.
Items:
- [ ] DOC-01 Rewrite README from the code: accurate stack, real `main.py` output, scoring rationale link, architecture diagram (Mermaid), “Known limitations” section, measured numbers only; delete references to missing files or add `LICENSE` — S
- [ ] Redeploy; `/health` endpoint; verify the Runbook works on the live URL; retake screenshots — S
- [ ] Re-run the `project-interview-report` skill, then `project-mock-interview` — S
Acceptance criteria:
- Every README claim maps to code or a measured output. A fresh clone works by following the README in < 10 minutes.
Verification commands:
- Fresh `git clone` into a temp dir and follow the README verbatim.
Interview payoff:
- A recruiter-clickable demo that holds up when an engineer opens the code.
Risk / rollback:
- Render free-tier cold start. Mention it upfront when demoing.

---

## Upgrades I’m Deliberately NOT Recommending

| Idea | Why not for this project |
|---|---|
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
