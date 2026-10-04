# DevTelemetry

> AI-powered usage analytics agent that tracks Claude Code token efficiency across engineering teams, scores developer habits, and auto-generates personalised cost-reduction guides.

![Python](https://img.shields.io/badge/Python-3.13-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green?style=flat-square&logo=fastapi)
![Gemini](https://img.shields.io/badge/Gemini-3.8_Flash-orange?style=flat-square&logo=google)
![SQLite](https://img.shields.io/badge/SQLite-3-lightgrey?style=flat-square&logo=sqlite)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)
![Live](https://img.shields.io/badge/Live-Render-46E3B7?style=flat-square&logo=render)

---

## The Problem

Engineering teams using AI coding tools like Claude Code have no visibility into whether their usage is efficient or wasteful. Based on Anthropic's published benchmarks, teams spend **$150–250 per developer per month** on AI tool tokens — with the top 10% of users spending 2–3× the average. The root causes are identifiable and fixable: poor prompt caching, defaulting to expensive models for simple tasks, and never using context management commands. But nobody is tracking them.

Managers cannot answer "is our AI investment worth it?" Engineers have no feedback on their habits. Cost spirals silently.

---

## What DevTelemetry Does

DevTelemetry runs as a daily agent that:

1. **Ingests usage telemetry** for each engineer (token counts, model usage, cache performance, session patterns)
2. **Scores each developer** on a weighted efficiency metric — not just spend, but quality of AI usage habits
3. **Ranks the team** on a live leaderboard dashboard with 30-day trend charts
4. **Generates personalised AI guides** using the Gemini API — specific to each engineer's actual waste patterns, not generic advice
5. **Dispatches automated reports** — a detailed leaderboard to the manager and individual efficiency guides to each engineer

---

## Demo

![Team Overview Dashboard](screenshots/dashboard-overview.png)

![Team Leaderboard](screenshots/dashboard-leaderboard.png)

![AI Optimization Runbook](screenshots/ai-runbook.png)


🔗 **[Live Demo → devtelemetry-1.onrender.com](https://devtelemetry-1.onrender.com/)**

> ⚠️ Hosted on Render free tier — may take 30–60 seconds to wake up on first load.

> **Note:** This project uses synthetic data modelled on Anthropic's published enterprise usage benchmarks. The data generation layer simulates realistic engineering team behaviour — the scoring engine, AI guide generator, dashboard, and notification pipeline are all fully functional.

```
$ python main.py

Running DevTelemetry daily agent — 2024-01-15
──────────────────────────────────────────────
Scoring 10 engineers...

Rank  Engineer        Score    Tokens      Est. Cost   Waste Pattern
1     Priya S.        87.4     142,000     $1.84       —
2     Aiko T.         79.1     198,000     $2.57       Low Haiku usage
3     Sofia M.        71.3     225,000     $2.92       Infrequent /compact
4     Rahul K.        58.6     287,000     $5.18       Mixed model usage
5     James L.        47.2     318,000     $7.64       Low cache hit ratio
6     Marcus B.       31.8     394,000     $14.20      No caching, heavy Opus
...

Generating AI guides for bottom 3 engineers...
  ✓ Guide generated for James L.
  ✓ Guide generated for Marcus B.
  ✓ Guide generated for Chen W.

Sending manager report via email... ✓
Dashboard updated at http://localhost:8000 ✓
```

**Sample AI-generated guide output:**

```
GUIDE FOR: Marcus B. | Score: 31.8/100 | Cost today: $14.20

Headline: You're spending 6× the team average — three fixable habits are
the entire reason.

1. PROMPT CACHING — saves ~85% on repeated input tokens
   Problem: Your cache hit ratio is 6% vs team average of 58%.
   Fix: Add a CLAUDE.md file to your project root with your coding
        standards and architecture notes. Claude will cache this
        automatically on every session.
   Estimated saving: 50–70% token reduction

2. MODEL SELECTION — Haiku costs 15× less than Opus
   Problem: You're using Opus for 45% of tasks including simple ones.
   Fix: Use /model in Claude Code to switch. Opus only for architecture
        decisions. Sonnet for complex logic. Haiku for tests, docs,
        simple refactors.
   Estimated saving: 30–40% cost reduction

3. CONTEXT MANAGEMENT — /compact prevents quadratic cost growth
   Problem: 0 uses of /compact across 4 sessions today.
   Fix: Run /compact every 30 minutes on long sessions or between
        major task switches. Reduces context by 60–80%.
   Estimated saving: 20–35% on long sessions
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Daily Agent                        │
│                     (main.py)                           │
└──────────┬──────────────┬─────────────────┬────────────┘
           │              │                 │
    ┌──────▼──────┐ ┌─────▼──────┐  ┌──────▼──────┐
    │   Data      │ │  Scoring   │  │     AI      │
    │  Generator  │ │   Engine   │  │    Guide    │
    │ (seed.py)   │ │(scorer.py) │  │ Generator   │
    └──────┬──────┘ └─────┬──────┘  └──────┬──────┘
           │              │                 │
           └──────────────▼─────────────────┘
                          │
                   ┌──────▼──────┐
                   │   SQLite    │
                   │  Database   │
                   └──────┬──────┘
                          │
           ┌──────────────┼─────────────────┐
           │              │                 │
    ┌──────▼──────┐ ┌─────▼──────┐  ┌──────▼──────┐
    │  FastAPI    │ │   Email    │  │    Slack    │
    │  Dashboard  │ │   Report   │  │    Post     │
    └─────────────┘ └────────────┘  └─────────────┘
```

---

## Efficiency Scoring Formula

Each engineer receives a daily score from 0–100:

```
efficiency_score = (cache_hit_ratio   × 40)
                 + (model_mix_score   × 30)
                 + (session_discipline × 30)
```

| Factor | What it measures | Target |
|---|---|---|
| `cache_hit_ratio` | `cache_read_tokens / total_input_tokens` | ≥ 60% |
| `model_mix_score` | Weighted penalty for Opus on simple tasks | ≤ 20% Opus |
| `session_discipline` | `/compact` usage rate and session length control | ≥ 1× per long session |

This rewards **efficient habits**, not just low spend — a productive engineer using many tokens correctly scores higher than an idle one.

---

## Project Structure

```
devtelemetry/
├── .env                      # API keys (never committed)
├── .gitignore
├── README.md
├── requirements.txt
├── main.py                   # daily agent entry point
│
├── data/
│   ├── seed.py               # synthetic data generator
│   ├── schema.sql            # database schema
│   └── usage.db              # SQLite database (gitignored)
│
├── core/
│   ├── models.py             # Engineer, DailyUsage dataclasses
│   ├── scorer.py             # efficiency_score() function
│   ├── leaderboard.py        # ranking and sorting logic
│   └── db.py                 # database read/write helpers
│
├── ai/
│   ├── guide_generator.py    # Gemini API integration
│   └── prompts.py            # all system prompts as constants
│
├── notifications/
│   ├── email_report.py       # HTML manager digest
│   └── slack_post.py         # team channel announcement
│
├── api/
│   └── main.py               # FastAPI app and routes
│
├── frontend/
│   ├── index.html            # leaderboard + Chart.js trends
│   ├── guide.html            # personal guide page
│   └── style.css
│
└── tests/
    ├── test_scorer.py
    └── test_generator.py
```

---

## Getting Started

### Prerequisites

- Python 3.13+ (3.13 in Docker; CI also tests 3.14)
- A free Gemini API key from [aistudio.google.com](https://aistudio.google.com)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/Priyanshh1407/devtelemetry.git
cd devtelemetry

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Add your GEMINI_API_KEY to .env

# 5. Seed the database with 30 days of synthetic data
python data/seed.py

# 6. Run the daily agent
python main.py
```

### Start the Dashboard

```bash
uvicorn api.main:app --reload
# Open http://localhost:8000
```

---

## GitHub Actions (CI and scheduled alerts)

Two workflows live in `.github/workflows/`:

| Workflow | Runs when | What it does |
|---|---|---|
| **CI** (`ci.yml`) | every push and pull request | Backend: ruff + pytest (Python 3.13 and 3.14, coverage must stay ≥ 85%). Frontend: ESLint + Vitest + production build. Needs no secrets. |
| **Scheduled alerts tick** (`scheduled-alerts.yml`) | every 15 minutes (only from the default branch) | Calls `POST /api/scheduled-tick`; the API sends the saved alert schedule at most once per slot. Needs the repository secrets `DEVTELEMETRY_API_URL` and `DEVTELEMETRY_ADMIN_TOKEN`. |

### Turning GitHub Actions off

| How | Stops | Manual "Run workflow" |
|---|---|---|
| **Repository variable** (soft switch): Settings → Secrets and variables → Actions → **Variables** → set `CI_ENABLED` or `SCHEDULED_ALERTS_ENABLED` to exactly `false`. Delete it (or set `true`) to turn it back on. | Automatic runs of that workflow (they show as *skipped*) | Still works |
| **Disable button** (hard switch): Actions tab → pick the workflow → `...` → **Disable workflow** (**Enable workflow** to undo). Everything: Settings → Actions → General → **Disable actions**. | All runs of that workflow (or all workflows) | Blocked |
| **One push only:** put `[skip ci]` in the commit message. | CI for that push | n/a |

From a terminal with the GitHub CLI:

```bash
gh variable set SCHEDULED_ALERTS_ENABLED --body false   # soft off
gh variable delete SCHEDULED_ALERTS_ENABLED             # back on (unset = on)
gh workflow disable "CI"                                # hard off
gh workflow enable "CI"
```

Notes: the value must be exactly `false` (other spellings count as on). If CI is a *required* check for merging, GitHub treats skipped jobs as passing, so only switch CI off temporarily. `tests/test_workflows.py` fails if any workflow job is missing its switch.

---

## Sending real usage data

`POST /api/ingest` (admin token in `X-Admin-Token`) accepts up to 1,000 records per request, one per engineer per day. Field names follow Anthropic's `usage` object (`input_tokens` = uncached; see [docs/scoring.md](docs/scoring.md)):

```json
{"records": [{"user_id": "ada", "date": "2026-10-03", "name": "Ada Lovelace", "email": "ada@example.com",
  "input_tokens": 400000, "output_tokens": 30000, "cache_read_tokens": 2500000, "cache_write_tokens": 150000,
  "opus_pct": 0.2, "sonnet_pct": 0.6, "haiku_pct": 0.2, "session_count": 4, "compact_uses": 2, "git_commits": 3}]}
```

- **Idempotent:** resending a day updates it instead of duplicating it, and the engineer's scores are recomputed (the `/compact` term pools 7 days).
- **Validated per record:** negative counts, model shares that don't sum to 1, `compact_uses > session_count`, future dates, unknown fields and client-supplied cost or score are rejected. The response lists each rejected record by index with reasons; the rest are still written.
- **Server-side cost and score:** cost uses the dated Anthropic price table (`core/pricing.py`), recorded per row in `cost_price_version`.
- `name` and `email` are required the first time an engineer appears.
- The simulator (`data/seed.py`) writes through the same code path. Measured: 10,000 records in ~0.7 s on SQLite (~15k records/s).

---

## AI provider

Coaching guides and team memos are generated with **Gemini** (`gemini-3.8-flash` by default; set `GEMINI_MODEL` to change it). Prices per model and date are in `ai/providers.py`, and every request is metered (`GET /api/ai-stats`).

The pipeline talks to a small `GuideProvider` interface (`generate(prompt, json_schema) -> text + usage + cost`), so adding another provider (e.g. Claude) means writing one class. Only the Gemini implementation exists today.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| AI Guide Generation | Google Gemini 3.8 Flash (structured JSON output, metered) |
| Web API | FastAPI + Uvicorn |
| Database | SQLite (built-in) |
| Frontend | React 18 + Vite |
| UI Styling | Tailwind CSS / CSS Modules |
| Fake Data | Faker library |
| Email Reports | smtplib / Gmail SMTP |
| Deployment | Render (free tier) |

---

## Roadmap

- [x] Synthetic data generator with realistic benchmarks
- [x] Weighted efficiency scoring engine
- [x] AI-generated personalised guides via Gemini API
- [x] FastAPI dashboard with Chart.js trend charts
- [x] Automated manager email report
- [ ] Slack bot integration (`/myusage` command)
- [ ] Week-over-week improvement tracking
- [ ] Budget threshold alerts
- [x] Telemetry ingestion API (`POST /api/ingest`)
- [ ] Claude provider (implement `GuideProvider`)
- [ ] Before/after simulation for ROI measurement

---

## Context and Motivation

This project was built to explore a real gap: engineering managers adopting AI coding tools have no instrumentation layer to understand usage patterns, identify waste, or measure whether the investment is working. DevTelemetry is a prototype of what that instrumentation layer could look like.

The data layer is intentionally synthetic — modelled on Anthropic's published enterprise benchmarks ($13/developer/active day average, 90th percentile at $30/day) — because real company telemetry is not accessible to an independent developer. The AI guide generation, scoring engine, dashboard, and notification pipeline are all fully functional against that synthetic data.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

*Built by Priyansh Waghela · [LinkedIn](https://www.linkedin.com/in/priyansh-waghela-3b754b282/) 