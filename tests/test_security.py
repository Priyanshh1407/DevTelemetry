"""SEC-01: side-effecting endpoints require an admin token; dispatch is rate limited; CORS is explicit."""
import threading

import pytest

import api.routes as routes

NEW_SCHEDULE = {"frequency": "Daily", "day": "Monday", "time": "09:30"}


@pytest.fixture
def stub_dispatch(monkeypatch):
    """Replaces the real worker with one that 'sends' one email, and counts calls."""
    calls = []

    def fake_run():
        calls.append(1)
        return {"engineers": 1, "developer_emails": {"sent": 1, "failed": 0, "skipped": 0},
                "failed_recipients": [], "manager_digest": "sent", "slack": "skipped"}

    monkeypatch.setattr(routes, "run_weekly_telemetry_check", fake_run)
    return calls


# ── Authentication ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/settings", NEW_SCHEDULE),
    ("post", "/api/trigger-alerts", None),
])
def test_admin_endpoints_reject_missing_token(client, admin_token, stub_dispatch, method, path, body):
    response = getattr(client, method)(path, json=body)

    assert response.status_code == 401
    assert stub_dispatch == []


def test_wrong_token_is_rejected(client, admin_token, stub_dispatch):
    response = client.post("/api/trigger-alerts", headers={"X-Admin-Token": "guess"})

    assert response.status_code == 401
    assert stub_dispatch == []


def test_admin_actions_fail_closed_when_server_has_no_token(client, stub_dispatch):
    # ADMIN_TOKEN is unset (conftest removes it): nobody can trigger, not even with a header.
    response = client.post("/api/trigger-alerts", headers={"X-Admin-Token": ""})

    assert response.status_code == 503
    assert stub_dispatch == []


def test_valid_token_is_accepted(client, admin_headers):
    assert client.post("/api/settings", json=NEW_SCHEDULE, headers=admin_headers).status_code == 200
    assert client.get("/api/settings").json() == {**NEW_SCHEDULE, "timezone": "UTC"}


def test_reading_settings_stays_public(client, admin_token):
    assert client.get("/api/settings").status_code == 200


# ── Dispatch abuse protection (single flight + cooldown, enforced by the dispatch_runs table) ──

def test_second_dispatch_within_cooldown_is_rejected(client, seeded_db, admin_headers, stub_dispatch):
    first = client.post("/api/trigger-alerts", headers=admin_headers)
    second = client.post("/api/trigger-alerts", headers=admin_headers)

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    assert len(stub_dispatch) == 1


def test_skipped_dispatch_does_not_start_cooldown(client, seeded_db, admin_headers):
    # Nothing configured -> nothing delivered -> the admin can fix config and retry immediately.
    first = client.post("/api/trigger-alerts", headers=admin_headers).json()
    assert client.get(first["status_url"]).json()["status"] == "skipped"
    assert client.post("/api/trigger-alerts", headers=admin_headers).status_code == 202


def test_dispatch_already_running_is_rejected(client, seeded_db, admin_headers, stub_dispatch):
    from core.dispatch import start_run

    start_run("manual")  # e.g. a scheduled or manual run still sending

    response = client.post("/api/trigger-alerts", headers=admin_headers)

    assert response.status_code == 409
    assert stub_dispatch == []


def test_concurrent_triggers_dispatch_once(client, seeded_db, admin_headers, monkeypatch):
    calls, release = [], threading.Event()

    def slow_run():
        calls.append(1)
        release.wait(5)
        return {"engineers": 1, "developer_emails": {"sent": 1, "failed": 0, "skipped": 0},
                "failed_recipients": [], "manager_digest": "sent", "slack": "skipped"}

    monkeypatch.setattr(routes, "run_weekly_telemetry_check", slow_run)
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        client.post("/api/trigger-alerts", headers=admin_headers).status_code)) for _ in range(5)]
    for t in threads:
        t.start()
    while not calls:
        pass
    release.set()
    for t in threads:
        t.join()

    assert len(calls) == 1
    assert results.count(202) == 1
    # The rest are rejected as busy (409) or, if they arrive after it finished, by the cooldown (429).
    assert set(results) - {202} <= {409, 429}


# ── CORS ────────────────────────────────────────────────────────────────────

def _preflight(client, origin):
    return client.options("/api/settings", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-admin-token"})


def test_cors_allows_configured_frontend(client):
    response = _preflight(client, "http://localhost:5173")

    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_rejects_unknown_origin(client):
    response = _preflight(client, "https://evil.example")

    assert response.headers.get("access-control-allow-origin") is None
