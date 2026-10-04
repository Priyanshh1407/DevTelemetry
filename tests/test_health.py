"""Phase 7: GET /health for the host's health check (Render) and quick manual checks.

It proves the database is reachable and migrated, and says whether AI is configured,
without revealing any secret."""
import sqlite3


def test_healthy_service_reports_ok(client, seeded_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "a-secret-value")

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["scoring_version"] == "3"
    assert body["latest_data_date"] == "2026-01-03"
    assert body["ai_configured"] is True
    assert "a-secret-value" not in response.text


def test_empty_database_is_still_healthy(client, empty_db):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["latest_data_date"] is None and body["ai_configured"] is False


def test_unreachable_database_answers_503(client, monkeypatch):
    import api.main as main

    def broken():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(main, "db_session", broken)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unreachable"}
    assert "unable to open" not in response.text   # internal details stay in the log
