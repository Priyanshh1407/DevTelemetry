from fastapi import APIRouter, HTTPException,Depends
from core.db import get_db_connection
from ai.guide_generator import generate_efficiency_guide
from pydantic import BaseModel
import asyncio
from data.alert_worker import run_weekly_telemetry_check

router = APIRouter()

@router.get("/leaderboard")
def get_leaderboard():
    with get_db_connection() as conn:
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
        
        return [dict(row) for row in cursor.fetchall()]

@router.get("/trends")
def get_team_trends():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Calculate daily averages for the chart
        cursor.execute("""
            SELECT date, 
                   ROUND(AVG(efficiency_score), 2) as avg_score, 
                   ROUND(SUM(estimated_cost_usd), 2) as total_cost
            FROM usage_metrics
            GROUP BY date
            ORDER BY date ASC
            LIMIT 30
        """)
        return [dict(row) for row in cursor.fetchall()]

@router.get("/guide/{user_id}")
def get_user_guide(user_id: str):
    with get_db_connection() as conn:
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
        
        # Generate the guide dynamically
        guide_text = generate_efficiency_guide(eng_dict, severity="moderate")
        
        return {
            "name": eng_dict["name"],
            "date": eng_dict["date"],
            "guide": guide_text
        }
    
# Defines the shape of the data coming from React
class AlertSchedule(BaseModel):
    frequency: str
    day: str
    time: str

@router.get("/settings")
def get_alert_settings():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT frequency, day, time FROM alert_settings WHERE id = 1")
        settings = cursor.fetchone()
        if settings:
            return dict(settings)
        return {"frequency": "Weekly", "day": "Friday", "time": "17:00"}

@router.post("/settings")
def update_alert_settings(schedule: AlertSchedule):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE alert_settings 
            SET frequency = ?, day = ?, time = ? 
            WHERE id = 1
        """, (schedule.frequency, schedule.day, schedule.time))
        conn.commit()
    return {"status": "success", "message": "Schedule updated"}

@router.post("/trigger-alerts")
def trigger_alerts():
    try:
        run_weekly_telemetry_check()
        return {"status": "success", "message": "All alerts successfully dispatched!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/engineer/{user_id}/details")
def get_engineer_details(user_id: str):
    with get_db_connection() as conn:
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
            
            # Severity logic
            if current_rank <= 5:
                current_severity = "low"
            elif current_rank >= total_team_size - 1:
                current_severity = "critical"
            else:
                current_severity = "moderate"
        
        # 3. Fetch 30-day history for the engineer
        cursor.execute("""
            SELECT date, efficiency_score, estimated_cost_usd, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, opus_pct, sonnet_pct, haiku_pct,
                   session_count, compact_uses, git_commits
            FROM usage_metrics
            WHERE user_id = ?
            ORDER BY date ASC
            LIMIT 30
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

ai_task_cache = {}

@router.get("/runbook-tasks/{severity}/{user_id}")
# Deliberately sync: the DB and Gemini calls below block, and FastAPI runs plain `def`
# handlers in a threadpool. As `async def`, they ran on the event loop and stalled every
# other request for the length of the LLM call.
def get_personalized_tasks(severity: str, user_id: str):
    # 2. Check the cache FIRST. If we already generated this user's tasks, return them instantly!
    cache_key = f"{user_id}_{severity}"
    if cache_key in ai_task_cache:
        print(f"[CACHE HIT] Returning instant tasks for {user_id}")
        return {"tasks": ai_task_cache[cache_key]}

    print(f"[CACHE MISS] Asking Gemini to generate tasks for {user_id}...")
    
    # 3. Connect to DB to get the latest metrics for this specific dev
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM usage_metrics 
        WHERE user_id = ? 
        ORDER BY date DESC LIMIT 1
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"tasks": [{"title": "Data Missing", "desc": "No telemetry found for this user."}]}

    engineer_data = dict(row)

    # 4. Call Gemini
    ai_tasks = generate_efficiency_guide(engineer_data, severity)
    
    # 5. Save the result in the cache so it's instant next time
    ai_task_cache[cache_key] = ai_tasks
    
    return {"tasks": ai_tasks}