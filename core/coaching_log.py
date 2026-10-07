"""The record of who was coached (UPG-05): written by the alert worker and the simulator,
read by GET /api/coaching-impact and the engineer page."""
from datetime import date, datetime, timezone


def record_coaching(conn, user_id, coached_on, severity, target_area, source):
    """Idempotent per engineer and day: a re-sent dispatch does not count as a second coaching."""
    conn.execute("""
        INSERT OR IGNORE INTO coaching_events (user_id, coached_on, severity, target_area, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, coached_on, severity, target_area, source,
          datetime.now(timezone.utc).isoformat(timespec="seconds")))


def coaching_events(conn, since=None, user_id=None):
    """Events as dicts with coached_on as a date, oldest first."""
    sql, params = "SELECT user_id, coached_on, severity, target_area, source FROM coaching_events WHERE 1 = 1", []
    if since is not None:
        sql += " AND coached_on >= ?"
        params.append(since.isoformat())
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY coached_on, user_id", params)]
    for r in rows:
        r["coached_on"] = date.fromisoformat(r["coached_on"])
    return rows
