import logging
import os
import sys

# Ensure Python can find your AI and Notification modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db_session
from core.queries import latest_day_rows
from core.severity import severity_for_rank
from ai.guide_generator import generate_team_report
from notifications.email_report import send_daily_report, send_developer_alert, smtp_session
from notifications.slack_post import send_slack_summary

logger = logging.getLogger(__name__)

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
    logger.info("Starting telemetry review")
    summary = {
        "engineers": 0,
        "developer_emails": {"sent": 0, "failed": 0, "skipped": 0},
        "failed_recipients": [],
        "manager_digest": "skipped",
        "slack": "skipped",
    }
    
    # --- 1. CONNECT TO THE LIVE DATABASE ---
    with db_session() as conn:
        all_devs = latest_day_rows(conn)
    
    total_devs = len(all_devs)
    if total_devs == 0:
        logger.warning("No usage data in the database; nothing to send")
        return summary

    logger.info("Loaded the latest day for %s engineers", total_devs)
    summary["engineers"] = total_devs

    # --- 2. CLASSIFY EACH DEVELOPER BY SEVERITY TIER ---
    for rank_index, dev in enumerate(all_devs):
        rank = rank_index + 1
        dev["rank"] = rank
        dev["total_devs"] = total_devs
        
        dev["severity"] = severity_for_rank(rank, total_devs)
        
        logger.info("#%s %s: score %.1f, severity %s", rank, dev["name"], dev["efficiency_score"], dev["severity"])

    # --- 3. DIAGNOSE WASTE PATTERNS FOR BOTTOM PERFORMERS ---
    # (Everything the emails need is prepared before the SMTP connection opens, so the
    # connection isn't held idle during the Gemini call.)
    logger.info("Compiling the manager digest")
    
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

    # --- 4. CALCULATE LIVE AGGREGATES FOR MANAGER ---
    total_score = sum(dev['efficiency_score'] for dev in all_devs)
    total_cost = sum(dev['estimated_cost_usd'] for dev in all_devs)
    team_avg = total_score / total_devs

    # --- 5. GENERATE AI SUMMARY ---
    logger.info("Requesting the AI team summary")
    team_summary_data = {
        "average_score": team_avg,
        "total_spend": total_cost,
        "critical_count": len(bottom_engineers)
    }
    ai_memo = generate_team_report(team_summary_data)

    # --- 6. SEND ALL EMAILS OVER ONE SMTP CONNECTION ---
    logger.info("Sending developer alerts and the manager digest")
    with smtp_session() as smtp:
        for dev in all_devs:
            status = send_developer_alert(dev, session=smtp)
            summary["developer_emails"][status] += 1
            if status == "failed":
                summary["failed_recipients"].append(dev["name"])
        logger.info("Developer alerts: %s", summary["developer_emails"])

        summary["manager_digest"] = send_daily_report(
            top_engineers=top_engineers,
            bottom_engineers=bottom_engineers,
            average_score=team_avg,
            total_cost=total_cost,
            ai_summary=ai_memo,
            session=smtp,
        )

    # --- 7. SEND SLACK CHANNEL SUMMARY ---
    logger.info("Posting the Slack summary")
    summary["slack"] = send_slack_summary(all_devs, team_avg, total_cost)

    logger.info("Telemetry review complete: %s %s", overall_status(summary), summary)
    return summary

if __name__ == "__main__":
    run_weekly_telemetry_check()