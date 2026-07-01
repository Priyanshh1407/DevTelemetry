# DevTelemetry: Interview Study Guide

This document is designed to help you prepare for technical interviews. It breaks down the entire **DevTelemetry** project into clear, explainable concepts covering the architecture, data flow, AI integration, and deployment.

---

## 1. The Elevator Pitch (What did you build?)
**"I built DevTelemetry, an AI-powered observability platform designed to track and optimize how software engineering teams use Large Language Models (LLMs)."**

* **The Problem:** Companies are spending thousands of dollars on API tokens (like OpenAI or Anthropic) without knowing if their engineers are using them efficiently. Some engineers waste tokens by not using prompt caching, while others overuse expensive models when cheaper ones would suffice.
* **The Solution:** A full-stack pipeline that tracks individual developer token usage, calculates an "Efficiency Score", and uses an AI (Gemini) to automatically generate and email personalized coaching runbooks to developers, while sending high-level executive digests to management via Slack.

---

## 2. Tech Stack & Architecture
Be prepared to explain *why* you chose these tools:

* **Frontend:** React (Vite) + TailwindCSS + Recharts
  * *Why?* Vite provides incredibly fast hot-reloading. Tailwind allows for rapid, modern UI styling without jumping between CSS files. Recharts handles the data visualization easily.
* **Backend:** Python + FastAPI
  * *Why?* FastAPI is incredibly fast, modern, and has built-in async support which is perfect for a lightweight analytics API. It's quickly becoming the industry standard over Flask.
* **Database:** SQLite (Relational)
  * *Why?* For a lightweight portfolio project, a file-based SQL database is perfect. It allows complex `JOIN` and `GROUP BY` operations without the overhead of setting up Postgres.
* **AI Engine:** Google Gemini (via `google-generativeai` SDK)
  * *Why?* Used to synthesize raw JSON metrics into human-readable coaching advice.
* **Infrastructure:** Render (PaaS)
  * *Why?* Provides a clean separation of concerns (Static Site for React, Web Service for Python) with easy environment variable management.

---

## 3. The Core Pipelines

### A. The Data Pipeline (`data/seed.py`)
Since we don't have a live proxy intercepting real company API calls, we built a robust synthetic data generator.
* Uses the `Faker` library to generate realistic engineer profiles.
* Generates 30 days of historical token metrics (input/output tokens, cache hits, model percentages).
* **Crucial Logic:** The script initializes the SQLite database using `core/db.py` (`init_db()`), ensuring tables exist before inserting the massive dataset.

### B. The Scoring Engine (`core/scorer.py`)
This is the heart of the analytics. It calculates an **Efficiency Score (0-100)** for each developer using a weighted algorithmic formula.

**The Math Formula:**
```math
Total Score = Cache Score (40 pts) + Model Mix Score (30 pts) + Session Discipline Score (30 pts)

1. Cache Score = (cache_read_tokens / input_tokens) * 40
2. Model Score = ((haiku_pct * 1.0) + (sonnet_pct * 0.6) + (opus_pct * 0.1)) * 30
3. Discipline Score = (compact_uses / session_count) * 30
```

* **Cost Efficiency / Cache Utilization (40%):** Higher ratio of cached reads vs raw input tokens equals a higher score.
* **Model Discipline (30%):** Using cheaper, faster models (Haiku/Sonnet) instead of the expensive, heavy model (Opus) boosts the score.
* **Session Discipline (30%):** Measures how frequently the engineer uses the `/compact` command to clear unnecessary context windows during active sessions.

### C. The API Layer (`api/routes.py`)
Exposes the SQLite data to the React frontend.
* **`GET /api/leaderboard`**: Joins the `engineers` and `usage_metrics` tables to rank the team based on the latest day's efficiency score.
* **`GET /api/engineer/{user_id}/details`**: Fetches 30-day historical data for a specific user and calculates rolling averages.
* **`POST /api/trigger-alerts`**: A manual trigger that allows an admin to execute the backend notification worker synchronously.

### D. The AI Integration (`ai/guide_generator.py`)
Instead of sending developers raw data ("You used 50k tokens"), we use Gemini to coach them.
* We pass a strictly structured **Prompt string** containing the developer's exact JSON metrics.
* **System Instructions:** We instruct Gemini to act as a "Staff Engineer" and output the response in raw markdown so it renders beautifully in the frontend and emails.

### E. The Notification Worker (`data/alert_worker.py` & `notifications/`)
This acts as a cron-job/worker script.
1. Connects to the live database and ranks all developers into Severity Tiers (Low, Moderate, Critical).
2. Uses `smtplib` and `email.mime` to securely log into an SMTP server (Gmail) and dispatch beautifully styled HTML emails (`email_report.py`) individually to every developer.
3. Uses the `urllib` library to make a POST request to a Slack Webhook (`slack_post.py`), dropping an executive summary into a management channel.

---

## 4. Deployment & Infrastructure Concepts

If an interviewer asks about deployment:
* **The Separation:** The project is split into two independent cloud instances. The React app is compiled into static HTML/JS/CSS files and served via a CDN (Render Static Site). The Python FastAPI app runs in a Docker container (Render Web Service).
* **CORS (Cross-Origin Resource Sharing):** Because the frontend and backend live on different domains, the FastAPI backend explicitly configures `CORSMiddleware` to allow HTTP requests from the React domain.
* **Environment Variables:** Credentials (like SMTP passwords and Gemini API keys) are never hardcoded. They are injected at runtime via Render's environment settings. The frontend uses `import.meta.env.VITE_API_URL` to dynamically know where the backend lives.

---

## 5. Potential Interview Questions & Answers

> **Q: How did you handle the AI prompt generation to ensure it didn't hallucinate?**
> **A:** "I heavily constrained the prompt. Instead of asking it to 'give advice', I injected the exact JSON metrics of the developer into the prompt template and instructed Gemini to act as a strict Staff Engineer, outputting a specific 3-part markdown structure. By grounding the prompt in hard data, hallucinations were eliminated."

> **Q: Why did you use SQLite instead of PostgreSQL?**
> **A:** "For an MVP and portfolio scale, SQLite was the most pragmatic choice. It requires zero network overhead and infrastructure setup, allowing me to focus on the core logic and AI pipelines. The code uses standard SQL, so migrating to Postgres via SQLAlchemy in the future would be trivial."

> **Q: How would you scale this if a company with 1,000 developers wanted to use it?**
> **A:** "Currently, the `alert_worker.py` runs synchronously, sending emails one by one. For 1,000 developers, I would introduce a message queue like **RabbitMQ or Redis/Celery**. The main worker would just push 1,000 'send_email' tasks to the queue, and background workers would process them asynchronously. I'd also swap the native `smtplib` for a bulk email provider API like SendGrid."

> **Q: What was the hardest bug you faced during this project?**
> **A:** *(You can use the exact bug we just fixed!)* "When I deployed the project to Render, the frontend was stuck loading endlessly when trying to send emails. I checked the backend logs and saw `[Errno 101] Network is unreachable`. I realized that Render's free tier firewall silently drops outbound traffic on SMTP port 587 to prevent spam. I learned a lot about cloud platform networking constraints and how to debug them using timeouts and explicit print logging."
