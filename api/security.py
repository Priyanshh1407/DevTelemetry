"""Admin authentication and abuse protection for side-effecting endpoints.

The dashboard has no user accounts, so a single shared admin token (ADMIN_TOKEN) guards
the endpoints that change state or send email/Slack. It is deliberately simple: with
real users this would be per-user auth (OIDC/session) plus role checks.
"""
import os
import secrets
import threading
import time

from fastapi import Header, HTTPException


def require_admin(x_admin_token: str | None = Header(default=None)):
    """FastAPI dependency: 401 unless X-Admin-Token matches ADMIN_TOKEN.

    Fails closed: if the server has no ADMIN_TOKEN configured, admin actions are disabled
    (503) rather than open to everyone.
    """
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin actions are disabled: ADMIN_TOKEN is not configured.")
    # compare_digest takes the same time wherever the strings differ (no timing side channel).
    if not x_admin_token or not secrets.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token.")


class DispatchGuard:
    """Single-flight + cooldown for alert dispatch, so a double click, a retrying client or
    a leaked token can't send the same batch of emails over and over.

    In-process state: correct for this single-instance deployment. With several instances
    this would move to the database (or a lock in Redis).
    """

    def __init__(self, cooldown_seconds=None):
        self._cooldown_override = cooldown_seconds
        self.lock = threading.Lock()
        self.last_dispatch_at = None  # time.monotonic() of the last dispatch that delivered anything

    @property
    def cooldown_seconds(self):
        if self._cooldown_override is not None:
            return self._cooldown_override
        return int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))

    def seconds_until_allowed(self):
        if self.last_dispatch_at is None:
            return 0
        remaining = self.cooldown_seconds - (time.monotonic() - self.last_dispatch_at)
        return max(0, int(remaining + 0.999))

    def mark_dispatched(self):
        self.last_dispatch_at = time.monotonic()

    def reset(self):
        self.last_dispatch_at = None
