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


def without_pii(row):
    """The row minus fields that must never be sent to an external LLM."""
    return {k: v for k, v in row.items() if k != "email"}
