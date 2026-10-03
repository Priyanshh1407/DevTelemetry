"""Admin authentication and abuse protection for side-effecting endpoints.

The dashboard has no user accounts, so a single shared admin token (ADMIN_TOKEN) guards
the endpoints that change state or send email/Slack. It is deliberately simple: with
real users this would be per-user auth (OIDC/session) plus role checks.

Dispatch abuse protection (single flight, cooldown) lives in core/dispatch.py, enforced by
the database so it holds across restarts and processes.
"""
import os
import secrets

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
