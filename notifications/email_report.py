import logging
import os
import smtplib
from contextlib import contextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from jinja2 import Environment, FileSystemLoader, select_autoescape
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Email templates live in frontend/; resolve from this file, not the working directory.
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

def _template_env():
    # Autoescape: names and the LLM-written summary are untrusted text inside HTML emails.
    return Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))


SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


# Configuration is read when a function runs, not at import, so tests and runtime
# config changes control where mail goes (values frozen at import ignored both).
def _smtp_credentials():
    """Returns (sender, password, recipient) from the environment."""
    return os.getenv("EMAIL_SENDER"), os.getenv("EMAIL_PASSWORD"), os.getenv("EMAIL_RECIPIENT")


def _dashboard_url():
    """Base URL for links inside emails."""
    return os.getenv("FRONTEND_URL", "http://localhost:5173")


def _production_mode():
    return os.getenv("PRODUCTION_MODE", "false").lower() == "true"

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
    env = _template_env()
    template = env.get_template('email_template.html')
    
    return template.render(
        top_engineers=top_engineers,
        bottom_engineers=bottom_engineers,
        average_score=round(average_score, 1),
        total_team_cost=round(total_cost, 2),
        ai_team_summary=ai_summary,
        dashboard_url=_dashboard_url()
    )


def render_developer_email(dev_data):
    """Renders a personalized alert email for an individual developer."""
    env = _template_env()
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
        runbook_url=f"{_dashboard_url()}/runbook/{severity}/{dev_data['user_id']}",
        dashboard_url=_dashboard_url(),
        greeting_message=theme["greeting"],
        banner_color=theme["banner_color"],
        severity_bg=theme["severity_bg"],
        severity_text=theme["severity_text"],
        tip_bg=theme["tip_bg"],
        severity_icon=theme["severity_icon"]
    )


class SmtpSession:
    """One SMTP connection reused for a whole dispatch (previously: one connection + login per email).

    - A dropped connection is reopened once and that email retried.
    - If connecting or logging in fails, the session stays broken: later emails fail
      immediately instead of hammering Gmail with the same bad login a dozen times.
    """

    def __init__(self, sender, password):
        self.sender, self.password = sender, password
        self.server = None
        self.broken = None  # the exception that made the session unusable

    def _connect(self):
        logger.info("Connecting to %s:%s", SMTP_SERVER, SMTP_PORT)
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(self.sender, self.password)
        self.server = server

    def send(self, to_address, message):
        if self.broken:
            raise self.broken
        if self.server is None:
            self._open()
        try:
            self.server.sendmail(self.sender, to_address, message)
        except smtplib.SMTPServerDisconnected:
            self.server = None
            self._open()
            self.server.sendmail(self.sender, to_address, message)
        # Any other error (e.g. one refused recipient) fails only this email.

    def _open(self):
        try:
            self._connect()
        except Exception as e:
            # Connect/login failures will fail every email the same way: remember and fail fast.
            self.broken = e
            raise

    def close(self):
        if self.server is not None:
            try:
                self.server.quit()
            except smtplib.SMTPException:
                pass
            self.server = None


@contextmanager
def smtp_session():
    """Yields an SmtpSession, or None when SMTP credentials aren't configured."""
    sender, password, recipient = _smtp_credentials()
    if not all([sender, password, recipient]):
        yield None
        return
    session = SmtpSession(sender, password)
    try:
        yield session
    finally:
        session.close()


def _deliver(session, to_address, msg, label):
    """Sends via the given session, or a one-off session if none. Returns "sent" or "failed"."""
    own_session = session is None
    if own_session:
        sender, password, _ = _smtp_credentials()
        session = SmtpSession(sender, password)
    try:
        session.send(to_address, msg.as_string())
        logger.info("%s sent to %s", label, to_address)
        return "sent"
    except Exception as e:
        logger.error("Failed to send %s: %s", label, e)
        return "failed"
    finally:
        if own_session:
            session.close()


def send_daily_report(top_engineers, bottom_engineers, average_score, total_cost, ai_summary, session=None):
    """Emails the manager digest. Returns "sent", "failed" or "skipped"."""
    sender, password, recipient = _smtp_credentials()
    if not all([sender, password, recipient]):
        logger.warning("SMTP credentials missing; skipping the manager digest")
        return "skipped"

    html_content = render_email_html(top_engineers, bottom_engineers, average_score, total_cost, ai_summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "DevTelemetry: Weekly Team Efficiency Digest"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_content, "html"))

    return _deliver(session, recipient, msg, "Executive digest")


def send_developer_alert(dev_data, session=None):
    """
    Sends a personalized efficiency alert email to an individual developer.

    In production: sends to the developer's own email (dev_data['email']).
    In demo mode:  sends to EMAIL_RECIPIENT so you can see all emails.
    Returns "sent", "failed" or "skipped".
    """
    sender, password, recipient = _smtp_credentials()
    if not all([sender, password, recipient]):
        logger.warning("SMTP credentials missing; skipping the alert for %s", dev_data["name"])
        return "skipped"

    html_content = render_developer_email(dev_data)

    # --- PRODUCTION TOGGLE ---
    # In production mode, we send directly to the engineer.
    # In demo mode, we route all emails to the test EMAIL_RECIPIENT.
    target_email = dev_data['email'] if _production_mode() else recipient

    severity = dev_data["severity"].upper()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{severity}] DevTelemetry: Your Efficiency Report — Rank #{dev_data['rank']}"
    msg["From"] = sender
    msg["To"] = target_email
    msg.attach(MIMEText(html_content, "html"))

    return _deliver(session, target_email, msg, f"Alert for {dev_data['name']}")
