import os
import sys

# Ensure Python can find your AI and Notification modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import get_db_connection
from core.severity import severity_for_rank
from ai.guide_generator import generate_team_report
from notifications.email_report import send_daily_report, send_developer_alert
from notifications.slack_post import send_slack_summary

def overall_status(summary):
    """Collapses a dispatch summary into one status: no_data, failed, skipped or success."""
    if summary["engineers"] == 0:
        return "no_data"
    statuses = [summary["manager_digest"], summary["slack"]]
    if summary["developer_emails"]["failed"] or "failed" in statuses:
        return "failed"
    if not summary["developer_emails"]["sent"] and "sent" not in statuses:
        return "skipped"
    return "success"


def run_weekly_telemetry_check():
    """Sends developer alerts, the manager digest and the Slack summary.

    Returns a summary of what was actually delivered, e.g.
    {"engineers": 10, "developer_emails": {"sent": 9, "failed": 1, "skipped": 0},
     "failed_recipients": ["..."], "manager_digest": "sent", "slack": "skipped"}
    """
    print("Initiating Industry-Grade Telemetry Review...\n")
    summary = {
        "engineers": 0,
        "developer_emails": {"sent": 0, "failed": 0, "skipped": 0},
        "failed_recipients": [],
        "manager_digest": "skipped",
        "slack": "skipped",
    }
    
    # --- 1. CONNECT TO THE LIVE DATABASE ---
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT e.name, e.email, u.efficiency_score, u.estimated_cost_usd, u.user_id, u.opus_pct
        FROM usage_metrics u
        JOIN engineers e ON u.user_id = e.user_id
        WHERE u.date = (SELECT MAX(date) FROM usage_metrics)
        ORDER BY u.efficiency_score DESC
    """)
    
    all_devs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    total_devs = len(all_devs)
    if total_devs == 0:
        print("❌ No data found in the database. Aborting.")
        return summary

    print(f"✅ Successfully pulled live data for {total_devs} engineers.\n")
    summary["engineers"] = total_devs

    # --- 2. CLASSIFY EACH DEVELOPER BY SEVERITY TIER ---
    print("--- CLASSIFYING DEVELOPERS BY SEVERITY ---")
    for rank_index, dev in enumerate(all_devs):
        rank = rank_index + 1
        dev["rank"] = rank
        dev["total_devs"] = total_devs
        
        dev["severity"] = severity_for_rank(rank, total_devs)
        
        icon = {"low": "🟢", "moderate": "🟡", "critical": "🔴"}[dev["severity"]]
        print(f"   {icon} [{dev['severity'].upper():>8}] #{rank} {dev['name']} — Score: {dev['efficiency_score']:.1f}")

    # --- 3. SEND INDIVIDUAL DEVELOPER ALERT EMAILS ---
    print("\n--- DISPATCHING INDIVIDUAL DEVELOPER ALERTS ---")
    
    for dev in all_devs:
        status = send_developer_alert(dev)
        summary["developer_emails"][status] += 1
        if status == "failed":
            summary["failed_recipients"].append(dev["name"])

    print(f"\nDeveloper alerts: {summary['developer_emails']}")

    # --- 4. DIAGNOSE WASTE PATTERNS FOR BOTTOM PERFORMERS ---
    print("\n--- COMPILING MANAGER EXECUTIVE DIGEST ---")
    
    top_engineers = all_devs[:5] 
    bottom_engineers = all_devs[-2:] 
    
    # Diagnose waste patterns for the email
    for dev in bottom_engineers:
        if dev['opus_pct'] > 0.50:
            dev['primary_waste_pattern'] = "Over-reliance on expensive Opus model"
        elif dev['efficiency_score'] < 60:
            dev['primary_waste_pattern'] = "High token waste / Possible prompt looping"
        else:
            dev['primary_waste_pattern'] = "Low cache utilization"

    # --- 5. CALCULATE LIVE AGGREGATES FOR MANAGER ---
    total_score = sum(dev['efficiency_score'] for dev in all_devs)
    total_cost = sum(dev['estimated_cost_usd'] for dev in all_devs)
    team_avg = total_score / total_devs

    # --- 6. GENERATE AI SUMMARY & FIRE MANAGER EMAIL ---
    print("🧠 Analyzing live telemetry via Gemini...")
    team_summary_data = {
        "average_score": team_avg,
        "total_spend": total_cost,
        "critical_count": len(bottom_engineers)
    }
    ai_memo = generate_team_report(team_summary_data)
    
    print("📧 Handoff complete. Sending Manager Digest via SMTP...")
    summary["manager_digest"] = send_daily_report(
        top_engineers=top_engineers,
        bottom_engineers=bottom_engineers,
        average_score=team_avg,
        total_cost=total_cost,
        ai_summary=ai_memo
    )

    # --- 7. SEND SLACK CHANNEL SUMMARY ---
    print("\n--- POSTING SLACK CHANNEL SUMMARY ---")
    summary["slack"] = send_slack_summary(all_devs, team_avg, total_cost)

    print(f"\n[DONE] Telemetry review complete: {overall_status(summary)} {summary}")
    return summary

if __name__ == "__main__":
    run_weekly_telemetry_check()