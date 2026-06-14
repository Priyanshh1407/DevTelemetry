import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "API is running"}

def test_get_leaderboard():
    response = client.get("/api/leaderboard")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 0

def test_get_engineer_details_not_found():
    response = client.get("/api/engineer/nonexistent_id/details")
    assert response.status_code == 404
    assert response.json() == {"detail": "Engineer not found"}

# We can't easily test a successful engineer details or runbook tasks without a known user_id.
# We'd ideally use a testing database setup or mock the db calls, but for this level of test,
# verifying the endpoints exist and handle errors is a good start.
