"""Read queries shared by the CLI agent (main.py) and the alert worker."""

LATEST_DAY_SQL = """
    SELECT e.name, e.email, u.*
    FROM usage_metrics u
    JOIN engineers e ON u.user_id = e.user_id
    WHERE u.date = (SELECT MAX(date) FROM usage_metrics)
    ORDER BY u.efficiency_score DESC
"""


def latest_day_rows(conn):
    """Every engineer's metrics for the most recent day, best score first, as dicts."""
    return [dict(row) for row in conn.execute(LATEST_DAY_SQL).fetchall()]


def latest_metrics_for_user(conn, user_id):
    """One engineer's most recent day of metrics (with their name), or None."""
    row = conn.execute("""
        SELECT u.*, e.name
        FROM usage_metrics u
        JOIN engineers e ON u.user_id = e.user_id
        WHERE u.user_id = ?
        ORDER BY u.date DESC LIMIT 1
    """, (user_id,)).fetchone()
    return dict(row) if row else None


def recent_metrics_for_user(conn, user_id, days=7):
    """One engineer's last `days` days of metrics, oldest first (empty list if none)."""
    rows = conn.execute("""
        SELECT * FROM usage_metrics WHERE user_id = ? ORDER BY date DESC LIMIT ?
    """, (user_id, days)).fetchall()
    return [dict(r) for r in reversed(rows)]


# Identity never leaves for the LLM: coaching needs the metrics, not who they belong to.
PII_FIELDS = ("name", "email")


def without_pii(row):
    """The row minus fields that must never be sent to an external LLM."""
    return {k: v for k, v in row.items() if k not in PII_FIELDS}


def recent_days_by_engineer(conn, days=30):
    """{user_id: [rows, oldest first]} for the `days` most recent dates in the database."""
    rows = conn.execute("""
        SELECT * FROM usage_metrics
        WHERE date > date((SELECT MAX(date) FROM usage_metrics), ?)
        ORDER BY date
    """, (f"-{days} days",)).fetchall()
    team = {}
    for r in rows:
        team.setdefault(r["user_id"], []).append(dict(r))
    return team
