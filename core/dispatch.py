"""Ledger of alert dispatches (table dispatch_runs).

Guarantees, enforced by the database rather than process memory, so they hold across
restarts and across processes:
- single flight: a partial unique index allows only one 'running' row;
- at most once per scheduled slot: UNIQUE(slot);
- cooldown for manual runs, measured from the last run that delivered (or tried to);
- a 'running' row older than STALE_AFTER (process killed mid-dispatch) is marked
  'abandoned' so it can't block dispatches forever.
"""
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from core.db import db_session

STALE_AFTER = timedelta(minutes=15)
DELIVERING = ("success", "failed")  # statuses that start the manual cooldown


class DispatchBusy(Exception):
    """Another dispatch is running."""


class DispatchCoolingDown(Exception):
    def __init__(self, retry_after):
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


class SlotAlreadyDispatched(Exception):
    """This scheduled slot already has a run."""


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def start_run(trigger, slot=None, cooldown_seconds=0, now=None):
    """Records a new 'running' dispatch and returns its id, or raises if it must not start."""
    now = now or _now()
    with db_session() as conn:
        # Take the write lock up front so the cooldown check and the insert are atomic.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE dispatch_runs SET status = 'abandoned', finished_at = ? WHERE status = 'running' AND started_at < ?",
            (_iso(now), _iso(now - STALE_AFTER)),
        )
        if cooldown_seconds:
            last = conn.execute(
                "SELECT MAX(finished_at) AS t FROM dispatch_runs WHERE status IN ('success', 'failed')"
            ).fetchone()["t"]
            if last:
                elapsed = (now - datetime.fromisoformat(last)).total_seconds()
                if elapsed < cooldown_seconds:
                    raise DispatchCoolingDown(math.ceil(cooldown_seconds - elapsed))
        try:
            cursor = conn.execute(
                "INSERT INTO dispatch_runs (trigger, slot, status, started_at) VALUES (?, ?, 'running', ?)",
                (trigger, slot, _iso(now)),
            )
        except sqlite3.IntegrityError as e:
            if "dispatch_runs.slot" in str(e):
                raise SlotAlreadyDispatched(slot) from e
            raise DispatchBusy() from e
        return cursor.lastrowid


def finish_run(run_id, status, summary=None, now=None):
    with db_session() as conn:
        conn.execute(
            "UPDATE dispatch_runs SET status = ?, finished_at = ?, summary_json = ? WHERE id = ?",
            (status, _iso(now or _now()), json.dumps(summary) if summary is not None else None, run_id),
        )


def get_run(run_id):
    with db_session() as conn:
        row = conn.execute("SELECT * FROM dispatch_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    run["summary"] = json.loads(run.pop("summary_json")) if run["summary_json"] else None
    return run
