import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

load_dotenv()

# Configuration from .env
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("EMAIL_SENDER")
SENDER_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL = os.getenv("EMAIL_RECIPIENT")

# Base URLs for links inside emails (use environment variable for production)
DASHBOARD_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
PRODUCTION_MODE = os.getenv("PRODUCTION_MODE", "false").lower() == "true"

# ─── Severity theme mapping ────────────────────────────────────────────────
SEVERITY_THEMES = {
    "low": {
        "banner_color": "#16a34a",
        "severity_bg": "#dcfce7",
        "severity_text": "#166534",
        "tip_bg": "#f0fdf4",
        "severity_icon": "🟢",
        "greeting": "Great work! You're among the top performers on the team. Keep leading by example.",
        "default_tip": "Consider mentoring teammates who are struggling with cache utilization — your patterns are worth sharing."
    },
    "moderate": {
        "banner_color": "#d97706",
        "severity_bg": "#fef3c7",
        "severity_text": "#92400e",
        "tip_bg": "#fffbeb",
        "severity_icon": "🟡",
        "greeting": "Your efficiency is in the middle range. A few small habit changes could push you into the top tier.",
        "default_tip": "Try using /compact more frequently between tasks to reset your context window and reduce token waste."
    },
    "critical": {
        "banner_color": "#dc2626",
        "severity_bg": "#fee2e2",
        "severity_text": "#991b1b",
        "tip_bg": "#fef2f2",
        "severity_icon": "🔴",
        "greeting": "Your usage patterns need immediate attention. Your efficiency score is significantly below the team average — please review your personalized runbook.",
        "default_tip": "Your cache hit ratio is very low. Ensure you're working within existing sessions rather than starting new ones for related tasks."
    }
}


def render_email_html(top_engineers, bottom_engineers, average_score, total_cost, ai_summary):
    """Loads the HTML template from the frontend folder and injects live data."""
    # Ensure 'email_template.html' is saved directly inside your 'frontend' folder
    env = Environment(loader=FileSystemLoader('frontend'))
    template = env.get_template('email_template.html')
    
    return template.render(
        top_engineers=top_engineers,
        bottom_engineers=bottom_engineers,
        average_score=round(average_score, 1),
        total_team_cost=round(total_cost, 2),
        ai_team_summary=ai_summary,
        dashboard_url=DASHBOARD_URL
    )


def render_developer_email(dev_data):
    """Renders a personalized alert email for an individual developer."""
    env = Environment(loader=FileSystemLoader('frontend'))
    template = env.get_template('dev_alert_template.html')
    
    severity = dev_data["severity"]
    theme = SEVERITY_THEMES.get(severity, SEVERITY_THEMES["moderate"])
    
    from datetime import date
    
    return template.render(
        name=dev_data["name"],
        date=date.today().strftime("%B %d, %Y"),
        rank=dev_data["rank"],
        total_devs=dev_data["total_devs"],
        score=round(dev_data["efficiency_score"], 1),
        cost=round(dev_data["estimated_cost_usd"], 2),
        severity=severity.upper(),
        rank_color="#16a34a" if dev_data["rank"] <= 5 else "#dc2626" if severity == "critical" else "#d97706",
        tip=dev_data.get("tip", theme["default_tip"]),
        runbook_url=f"{DASHBOARD_URL}/runbook/{severity}/{dev_data['user_id']}",
        dashboard_url=DASHBOARD_URL,
        greeting_message=theme["greeting"],
        banner_color=theme["banner_color"],
        severity_bg=theme["severity_bg"],
        severity_text=theme["severity_text"],
        tip_bg=theme["tip_bg"],
        severity_icon=theme["severity_icon"]
    )


def send_daily_report(top_engineers, bottom_engineers, average_score, total_cost, ai_summary):
    """Packages the HTML into an email and sends it via SMTP."""
    
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print("❌ SMTP Credentials missing in .env. Skipping email dispatch.")
        return

    html_content = render_email_html(top_engineers, bottom_engineers, average_score, total_cost, ai_summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "DevTelemetry: Weekly Team Efficiency Digest"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    part = MIMEText(html_content, "html")
    msg.attach(part)

    try:
        print(f"⏳ Attempting to connect to {SMTP_SERVER}:{SMTP_PORT} for Executive Digest...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        
        print(f"✅ Executive digest successfully emailed to {RECIPIENT_EMAIL}!")
        
    except Exception as e:
        print(f"❌ Failed to send email. Check your SMTP app password! Error: {e}")
        
    finally:
        try:
            server.quit()
        except:
            pass


def send_developer_alert(dev_data):
    """
    Sends a personalized efficiency alert email to an individual developer.
    
    In production: sends to the developer's own email (dev_data['email']).
    In demo mode:  sends to the RECIPIENT_EMAIL from .env so you can see all emails.
    """
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print(f"   ⚠️  SMTP credentials missing. Skipping email for {dev_data['name']}.")
        return
    
    html_content = render_developer_email(dev_data)

    # --- PRODUCTION TOGGLE ---
    # In production mode, we send directly to the engineer.
    # In demo mode, we route all emails to the test RECIPIENT_EMAIL from .env.
    target_email = dev_data['email'] if PRODUCTION_MODE else RECIPIENT_EMAIL
    
    severity = dev_data["severity"].upper()
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{severity}] DevTelemetry: Your Efficiency Report — Rank #{dev_data['rank']}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = target_email

    part = MIMEText(html_content, "html")
    msg.attach(part)

    try:
        print(f"   ⏳ Attempting to connect to {SMTP_SERVER}:{SMTP_PORT} for {dev_data['name']}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, target_email, msg.as_string())
        
        print(f"   📨 Alert sent to {dev_data['name']} ({target_email})")
        
    except Exception as e:
        print(f"   ❌ Failed to send alert to {dev_data['name']}: {e}")
        
    finally:
        try:
            server.quit()
        except:
            pass