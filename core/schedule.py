"""When is a scheduled alert due?

An external trigger (a GitHub Actions cron every 15 minutes, or data/clock.py locally)
asks "is a slot due now?". The answer is the most recent scheduled occurrence that has
passed but is no older than a grace window. Delivery is at most once per slot: the slot's
UTC time is stored with UNIQUE(slot) in dispatch_runs (see core/dispatch.py).

Times are wall-clock times in the schedule's IANA timezone, so DST shifts the UTC time
of the slot, not the local time people see.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def due_slot(frequency, day, time_str, tz_name, now_utc, grace):
    """Returns the due slot as an aware UTC datetime, or None if nothing is due.

    frequency: "Daily" or "Weekly" (day is ignored for Daily). time_str: "HH:MM".
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    hour, minute = (int(part) for part in time_str.split(":"))

    # Walk back from today (local) to the most recent occurrence at or before now.
    for days_back in range(8):
        date = (local_now - timedelta(days=days_back)).date()
        if frequency == "Weekly" and WEEKDAYS[date.weekday()] != day:
            continue
        occurrence = datetime(date.year, date.month, date.day, hour, minute, tzinfo=tz)
        if occurrence > local_now:
            continue
        # Only the most recent occurrence counts; if it's past the grace window, nothing is due.
        if local_now - occurrence <= grace:
            return occurrence.astimezone(timezone.utc)
        return None
    return None
