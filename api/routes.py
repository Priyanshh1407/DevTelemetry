from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Response
from core.db import db_session
from ai.guide_generator import generate_efficiency_guide
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from data.alert_worker import overall_status, run_weekly_telemetry_check
from api.security import require_admin
from core.severity import severity_for_rank
from core.queries import without_pii
from core.dispatch import (DispatchBusy, DispatchCoolingDown, SlotAlreadyDispatched, finish_run, get_run,
                           start_run)
from core.schedule import due_slot

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/leaderboard")
def get_leaderboard():
    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Find the most recent date in the database
        cursor.execute("SELECT MAX(date) as latest FROM usage_metrics")
        latest_date = cursor.fetchone()["latest"]

        if not latest_date:
            return []

        # 2. Fetch the ranked leaderboard for that specific day
        cursor.execute("""
            SELECT e.name, u.user_id, u.efficiency_score, u.estimated_cost_usd, 
                   u.input_tokens, u.output_tokens
            FROM usage_metrics u
            JOIN engineers e ON u.user_id = e.user_id
            WHERE u.date = ?
            ORDER BY u.efficiency_score DESC
        """, (latest_date,))
        board = [dict(row) for row in cursor.fetchall()]

        # 3. One window query for trends (no per-engineer queries): the latest day plus the 7 before it
        window = conn.execute("""
            SELECT user_id, date, efficiency_score, input_tokens
            FROM usage_metrics
            WHERE date BETWEEN date(?, '-7 days') AND ?
            ORDER BY date ASC
        """, (latest_date, latest_date)).fetchall()

    history = {}
    for r in window:
        history.setdefault(r["user_id"], []).append(r)

    for row in board:
        days = history.get(row["user_id"], [])
        previous = [d["efficiency_score"] for d in days if d["date"] < latest_date]
        # Latest score vs. the average of the previous 7 days; None when there is no history yet.
        row["score_change_7d"] = (round(row["efficiency_score"] - sum(previous) / len(previous), 2)
                                  if previous else None)
        # Last 7 days of prompt tokens (oldest first) for the dashboard's activity sparkline
        row["recent_activity"] = [d["input_tokens"] for d in days][-7:]
    return board

@router.get("/trends")
def get_team_trends():
    with db_session() as conn:
        cursor = conn.cursor()
        # Daily averages for the chart: the 30 MOST RECENT days, returned oldest-first.
        # (ORDER BY date ASC LIMIT 30 alone kept the 30 oldest days.)
        cursor.execute("""
            SELECT * FROM (
                SELECT date,
                       ROUND(AVG(efficiency_score), 2) as avg_score,
                       ROUND(SUM(estimated_cost_usd), 2) as total_cost
                FROM usage_metrics
                GROUP BY date
                ORDER BY date DESC
                LIMIT 30
            ) ORDER BY date ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

@router.get("/guide/{user_id}")
def get_user_guide(user_id: str):
    with db_session() as conn:
        cursor = conn.cursor()
        
        # Get the user's most recent metrics
        cursor.execute("""
            SELECT u.*, e.name 
            FROM usage_metrics u
            JOIN engineers e ON u.user_id = e.user_id
            WHERE u.user_id = ?
            ORDER BY date DESC LIMIT 1
        """, (user_id,))
        
        engineer_data = cursor.fetchone()
        
        if not engineer_data:
            raise HTTPException(status_code=404, detail="Engineer not found")
        
        # Convert sqlite3.Row to a standard dictionary for the AI generator
        eng_dict = dict(engineer_data)

    # Generate after the DB session closes: don't hold a connection open during an LLM call.
    # Only metrics go to the LLM, never the engineer's name or email.
    result = generate_efficiency_guide(without_pii(eng_dict), severity="moderate")

    return {
        "name": eng_dict["name"],
        "date": eng_dict["date"],
        "guide": result.tasks,
        "source": result.source
    }
    
# Defines the shape of the data coming from React
Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
Severity = Literal["low", "moderate", "critical"]


DEFAULT_SCHEDULE = {"frequency": "Weekly", "day": "Friday", "time": "17:00", "timezone": "UTC"}


class AlertSchedule(BaseModel):
    # Only frequencies the scheduler actually implements (Biweekly/Monthly never fired anywhere).
    frequency: Literal["Daily", "Weekly"]
    day: Weekday  # ignored for Daily
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="24-hour HH:MM")
    # Wall-clock times are in this IANA zone. Defaults to UTC for clients that don't send it.
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown IANA timezone: {value!r}") from None
        return value


def _read_schedule():
    with db_session() as conn:
        row = conn.execute("SELECT frequency, day, time, timezone FROM alert_settings WHERE id = 1").fetchone()
    return dict(row) if row else dict(DEFAULT_SCHEDULE)


@router.get("/settings")
def get_alert_settings():
    return _read_schedule()


@router.post("/settings", dependencies=[Depends(require_admin)])
def update_alert_settings(schedule: AlertSchedule):
    with db_session() as conn:
        # Upsert: also works if the singleton row was ever deleted.
        conn.execute("""
            INSERT INTO alert_settings (id, frequency, day, time, timezone) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET frequency = excluded.frequency, day = excluded.day,
                                          time = excluded.time, timezone = excluded.timezone
        """, (schedule.frequency, schedule.day, schedule.time, schedule.timezone))
    return {"status": "success", "message": "Schedule updated"}

def _dispatch_message(summary):
    emails = summary["developer_emails"]
    return (f"Developer alerts: {emails['sent']} sent, {emails['failed']} failed, {emails['skipped']} skipped. "
            f"Manager digest: {summary['manager_digest']}. Slack: {summary['slack']}.")


def _alert_cooldown_seconds():
    return int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))


def _has_usage_data():
    with db_session() as conn:
        return conn.execute("SELECT 1 FROM usage_metrics LIMIT 1").fetchone() is not None


def _describe_run(run):
    """Human-readable message for a dispatch run, for the dashboard toast."""
    status, summary = run["status"], run["summary"]
    if status == "running":
        return "Sending alerts..."
    if status == "success":
        return _dispatch_message(summary)
    if status == "failed":
        return "Some notifications failed. " + _dispatch_message(summary)
    if status == "skipped":
        return "Nothing was sent: email and Slack are not configured on the server."
    if status == "no_data":
        return "No usage data to report yet."
    if status == "abandoned":
        return "The dispatch was interrupted (server restart?) before it finished."
    return "Alert dispatch failed unexpectedly; see server logs."


def run_dispatch(run_id):
    """Background job: sends everything, then records the outcome on the run."""
    try:
        summary = run_weekly_telemetry_check()
    except Exception:
        # Log the details server-side; never store or return internals (paths, SQL, credentials).
        logger.exception("Alert dispatch %s crashed", run_id)
        finish_run(run_id, "error")
        return
    finish_run(run_id, overall_status(summary), summary)


@router.post("/trigger-alerts", status_code=202, dependencies=[Depends(require_admin)])
def trigger_alerts(background_tasks: BackgroundTasks):
    """Starts a dispatch and returns immediately; poll status_url for the outcome.

    Sending ~a dozen emails can take a minute; doing it inside the request risked proxy
    timeouts, and a client retry after a timeout would have sent everything twice.
    """
    if not _has_usage_data():
        raise HTTPException(status_code=409, detail="No usage data to report yet.")
    try:
        run_id = start_run("manual", cooldown_seconds=_alert_cooldown_seconds())
    except DispatchCoolingDown as e:
        raise HTTPException(status_code=429, headers={"Retry-After": str(e.retry_after)},
                            detail=f"Alerts were sent recently. Try again in {e.retry_after} seconds.") from e
    except DispatchBusy as e:
        raise HTTPException(status_code=409, detail="An alert dispatch is already running.") from e

    background_tasks.add_task(run_dispatch, run_id)
    return {"run_id": run_id, "status": "running", "status_url": f"/api/dispatch-runs/{run_id}"}


@router.get("/dispatch-runs/{run_id}")
def get_dispatch_run(run_id: int):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Dispatch run not found")
    run["message"] = _describe_run(run)
    return run


def _utcnow():
    return datetime.now(timezone.utc)


def _schedule_grace():
    # GitHub's cron can start runs late, and Render's free tier needs ~1 min to wake up.
    return timedelta(minutes=int(os.getenv("SCHEDULE_GRACE_MINUTES", "120")))


def start_scheduled_dispatch():
    """The scheduling decision, shared by the tick endpoint and data/clock.py.

    Returns {"status": ...}; when it is "started", the caller must run run_dispatch(run_id).
    Safe to call any number of times: each slot is sent at most once (UNIQUE slot).
    """
    schedule = _read_schedule()
    slot = due_slot(schedule["frequency"], schedule["day"], schedule["time"], schedule["timezone"],
                    now_utc=_utcnow(), grace=_schedule_grace())
    if slot is None:
        return {"status": "not_due"}
    slot_key = slot.isoformat()
    if not _has_usage_data():
        return {"status": "no_data", "slot": slot_key}
    try:
        # Scheduled runs skip the manual cooldown: the per-slot uniqueness is their guard.
        run_id = start_run("schedule", slot=slot_key)
    except SlotAlreadyDispatched:
        return {"status": "already_sent", "slot": slot_key}
    except DispatchBusy:
        # A manual dispatch is running. The slot wasn't consumed, so the next tick retries.
        return {"status": "busy", "slot": slot_key}
    return {"status": "started", "run_id": run_id, "slot": slot_key, "status_url": f"/api/dispatch-runs/{run_id}"}


@router.post("/scheduled-tick", dependencies=[Depends(require_admin)])
def scheduled_tick(background_tasks: BackgroundTasks, response: Response):
    """Called every ~15 minutes by an external cron (.github/workflows/scheduled-alerts.yml).

    Starts the scheduled dispatch if a slot is due. "Nothing to do" outcomes answer 200 so
    the cron job doesn't report failures for normal ticks; a started dispatch answers 202.
    """
    result = start_scheduled_dispatch()
    if result["status"] == "started":
        background_tasks.add_task(run_dispatch, result["run_id"])
        response.status_code = 202
    return result

@router.get("/engineer/{user_id}/details")
def get_engineer_details(user_id: str):
    with db_session() as conn:
        cursor = conn.cursor()
        
        # 1. Fetch engineer info
        cursor.execute("SELECT name, email FROM engineers WHERE user_id = ?", (user_id,))
        engineer = cursor.fetchone()
        if not engineer:
            raise HTTPException(status_code=404, detail="Engineer not found")
        
        # 2. Get the latest date in the DB to calculate rank
        cursor.execute("SELECT MAX(date) as latest FROM usage_metrics")
        latest_date = cursor.fetchone()["latest"]
        
        current_rank = 1
        total_team_size = 10
        current_severity = "moderate"
        
        if latest_date:
            cursor.execute("""
                SELECT user_id, efficiency_score 
                FROM usage_metrics 
                WHERE date = ? 
                ORDER BY efficiency_score DESC
            """, (latest_date,))
            leaderboard = cursor.fetchall()
            total_team_size = len(leaderboard)
            for idx, row in enumerate(leaderboard):
                if row["user_id"] == user_id:
                    current_rank = idx + 1
                    break
            
            current_severity = severity_for_rank(current_rank, total_team_size)
        
        # 3. Fetch the engineer's 30 most recent days, returned oldest-first
        cursor.execute("""
            SELECT * FROM (
                SELECT date, efficiency_score, estimated_cost_usd, input_tokens, output_tokens,
                       cache_read_tokens, cache_write_tokens, opus_pct, sonnet_pct, haiku_pct,
                       session_count, compact_uses, git_commits
                FROM usage_metrics
                WHERE user_id = ?
                ORDER BY date DESC
                LIMIT 30
            ) ORDER BY date ASC
        """, (user_id,))
        rows = cursor.fetchall()
        
        history = []
        for r in rows:
            h_dict = dict(r)
            # calculate cache ratio for this record
            input_toks = h_dict.get("input_tokens") or 0
            cache_read = h_dict.get("cache_read_tokens") or 0
            h_dict["cache_ratio"] = round(cache_read / input_toks, 4) if input_toks > 0 else 0.0
            history.append(h_dict)
            
        if not history:
            raise HTTPException(status_code=404, detail="No usage history found for this engineer")
            
        # 4. Compute Averages
        cnt = len(history)
        sum_score = sum(h["efficiency_score"] for h in history)
        sum_cost = sum(h["estimated_cost_usd"] for h in history)
        sum_cache_ratio = sum(h["cache_ratio"] for h in history)
        sum_sessions = sum(h["session_count"] for h in history)
        sum_commits = sum(h["git_commits"] for h in history)
        
        avg_compact_ratio = sum((h["compact_uses"] / h["session_count"] if h["session_count"] > 0 else 0) for h in history) / cnt
        
        averages = {
            "avg_score": round(sum_score / cnt, 2),
            "avg_cost": round(sum_cost / cnt, 2),
            "avg_cache_ratio": round(sum_cache_ratio / cnt, 4),
            "avg_sessions": round(sum_sessions / cnt, 1),
            "total_commits": sum_commits,
            "avg_compact_ratio": round(avg_compact_ratio, 4)
        }
        
        # 5. Latest Snapshot
        latest_record = history[-1]
        latest = {
            "efficiency_score": latest_record["efficiency_score"],
            "estimated_cost_usd": latest_record["estimated_cost_usd"],
            "cache_ratio": latest_record["cache_ratio"],
            "opus_pct": latest_record["opus_pct"],
            "sonnet_pct": latest_record["sonnet_pct"],
            "haiku_pct": latest_record["haiku_pct"]
        }
        
        # 6. Generate threshold-based insights (patterns)
        avg_opus = sum(h["opus_pct"] for h in history) / cnt
        patterns = []
        
        # Insight 1: Model Usage
        if avg_opus > 0.15:
            patterns.append({
                "label": "Model Usage",
                "insight": f"Uses Opus for {avg_opus * 100:.1f}% of requests — above team target of <15%"
            })
        else:
            patterns.append({
                "label": "Model Usage",
                "insight": f"Uses Opus for {avg_opus * 100:.1f}% of requests — within team target of <15%"
            })
            
        # Insight 2: Cache Efficiency
        avg_cache_pct = averages["avg_cache_ratio"] * 100
        if avg_cache_pct >= 60.0:
            patterns.append({
                "label": "Cache Efficiency",
                "insight": f"{avg_cache_pct:.1f}% cache hit ratio — strong reuse of prompt caching"
            })
        else:
            patterns.append({
                "label": "Cache Efficiency",
                "insight": f"{avg_cache_pct:.1f}% cache hit ratio — room to improve prompt caching and reuse"
            })
            
        # Insight 3: Session Discipline
        avg_comp = avg_compact_ratio * 100
        if avg_comp >= 50.0:
            patterns.append({
                "label": "Session Discipline",
                "insight": f"Uses /compact {avg_comp:.1f}% of sessions — strong context management habit"
            })
        else:
            patterns.append({
                "label": "Session Discipline",
                "insight": f"Uses /compact {avg_comp:.1f}% of sessions — recommend using /compact more often to keep context clean"
            })
            
        return {
            "name": engineer["name"],
            "email": engineer["email"],
            "current_rank": current_rank,
            "current_severity": current_severity,
            "latest": latest,
            "history": history,
            "averages": averages,
            "patterns": patterns
        }

# In-memory, per-process cache of successful AI guides only.
# Key: (user_id, date of their latest metrics, severity), so new data produces a new guide.
ai_task_cache = {}

# Deliberately sync: the DB and Gemini calls below block, and FastAPI runs plain `def`
# handlers in a threadpool. As `async def`, they ran on the event loop and stalled every
# other request for the length of the LLM call.
@router.get("/runbook-tasks/{severity}/{user_id}")
def get_personalized_tasks(severity: Severity, user_id: str):
    # 1. Get the latest metrics for this dev (cheap; needed for the cache key)
    with db_session() as conn:
        row = conn.execute("""
            SELECT * FROM usage_metrics
            WHERE user_id = ?
            ORDER BY date DESC LIMIT 1
        """, (user_id,)).fetchone()

    if not row:
        return {"tasks": [{"title": "Data Missing", "desc": "No telemetry found for this user."}], "source": "none"}

    engineer_data = dict(row)

    # 2. Serve from cache if this exact data was already turned into a guide
    cache_key = (user_id, engineer_data["date"], severity)
    if cache_key in ai_task_cache:
        print(f"[CACHE HIT] Returning instant tasks for {user_id}")
        return {"tasks": ai_task_cache[cache_key], "source": "ai"}

    print(f"[CACHE MISS] Asking Gemini to generate tasks for {user_id}...")

    # 3. Call Gemini
    result = generate_efficiency_guide(without_pii(engineer_data), severity)

    # 4. Cache only real answers. A fallback is returned but not stored, so the next
    #    request retries instead of serving an outage message until restart.
    if not result.is_fallback:
        ai_task_cache[cache_key] = result.tasks

    return {"tasks": result.tasks, "source": result.source}