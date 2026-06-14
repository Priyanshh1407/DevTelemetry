import sqlite3
import os
import sys

# Ensure Python can find your AI and Notification modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai.guide_generator import generate_team_report
from notifications.email_report import send_daily_report, send_developer_alert
from notifications.slack_post import send_slack_summary

def run_weekly_telemetry_check():
    print("Initiating Industry-Grade Telemetry Review...\n")
    
    # --- 1. CONNECT TO THE LIVE DATABASE ---
    db_path = os.path.join(os.path.dirname(__file__), 'usage.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
        return

    print(f"✅ Successfully pulled live data for {total_devs} engineers.\n")

    # --- 2. CLASSIFY EACH DEVELOPER BY SEVERITY TIER ---
    print("--- CLASSIFYING DEVELOPERS BY SEVERITY ---")
    for rank_index, dev in enumerate(all_devs):
        rank = rank_index + 1
        dev["rank"] = rank
        dev["total_devs"] = total_devs
        
        # Apply the exact 5/3/2 ranking logic from your React dashboard
        if rank <= 5:
            dev["severity"] = "low"
        elif rank >= (total_devs - 1):
            dev["severity"] = "critical"
        else:
            dev["severity"] = "moderate"
        
        icon = {"low": "🟢", "moderate": "🟡", "critical": "🔴"}[dev["severity"]]
        print(f"   {icon} [{dev['severity'].upper():>8}] #{rank} {dev['name']} — Score: {dev['efficiency_score']:.1f}")

    # --- 3. SEND INDIVIDUAL DEVELOPER ALERT EMAILS ---
    print("\n--- DISPATCHING INDIVIDUAL DEVELOPER ALERTS ---")
    
    for dev in all_devs:
        send_developer_alert(dev)
    
    print(f"\n✅ Individual alerts dispatched to {total_devs} developers.")

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
    send_daily_report(
        top_engineers=top_engineers,
        bottom_engineers=bottom_engineers,
        average_score=team_avg,
        total_cost=total_cost,
        ai_summary=ai_memo
    )

    # --- 7. SEND SLACK CHANNEL SUMMARY ---
    print("\n--- POSTING SLACK CHANNEL SUMMARY ---")
    send_slack_summary(all_devs, team_avg, total_cost)
    
    print("\n[DONE] Full telemetry review complete. All notifications dispatched.")

if __name__ == "__main__":
    run_weekly_telemetry_check()