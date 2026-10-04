"""UPG-02: telemetry ingestion API (validated, idempotent, cost and score computed server-side)."""
from datetime import date, timedelta

import pytest

from core.pricing import PRICE_TABLE_VERSION, estimate_cost
from core.scorer import score_history

TODAY = date.today()


def record(user="u1", day=None, **overrides):
    rec = {"user_id": user, "date": (day or TODAY - timedelta(days=1)).isoformat(),
           "name": "Ingested Engineer", "email": "ingested@example.com",
           "input_tokens": 400_000, "output_tokens": 30_000, "cache_read_tokens": 2_500_000,
           "cache_write_tokens": 150_000, "opus_pct": 0.2, "sonnet_pct": 0.6, "haiku_pct": 0.2,
           "session_count": 4, "compact_uses": 2, "git_commits": 3}
    rec.update(overrides)
    return rec


def ingest(client, records, headers):
    return client.post("/api/ingest", json={"records": records}, headers=headers)


def test_requires_the_admin_token(client, admin_token):
    assert client.post("/api/ingest", json={"records": [record()]}).status_code == 401


def test_valid_records_are_stored_with_server_computed_cost_and_score(client, admin_headers, query):
    response = ingest(client, [record()], admin_headers)

    assert response.status_code == 200
    assert response.json() == {"inserted": 1, "updated": 0, "rejected": []}
    row = query("SELECT * FROM usage_metrics")[0]
    rec = record()
    expected_cost = estimate_cost(rec["input_tokens"], rec["output_tokens"], rec["cache_read_tokens"],
                                  rec["cache_write_tokens"], {k: rec[k] for k in ("opus_pct", "sonnet_pct", "haiku_pct")})
    assert row["estimated_cost_usd"] == pytest.approx(expected_cost, abs=1e-4)
    assert row["cost_price_version"] == PRICE_TABLE_VERSION
    assert row["efficiency_score"] == score_history([row])[0]
    assert query("SELECT name, email FROM engineers") == [{"name": "Ingested Engineer", "email": "ingested@example.com"}]


def test_resending_a_batch_updates_instead_of_duplicating(client, admin_headers, query):
    batch = [record(day=TODAY - timedelta(days=d)) for d in (1, 2, 3)]

    first = ingest(client, batch, admin_headers).json()
    second = ingest(client, batch, admin_headers).json()

    assert (first["inserted"], second["inserted"], second["updated"]) == (3, 0, 3)
    assert query("SELECT COUNT(*) AS n FROM usage_metrics")[0]["n"] == 3


def test_a_correction_updates_the_row_and_rescores_the_following_days(client, admin_headers, query):
    days = [record(day=TODAY - timedelta(days=d), compact_uses=0) for d in (3, 2, 1)]
    ingest(client, days, admin_headers)
    before = query("SELECT date, efficiency_score FROM usage_metrics ORDER BY date")

    # A late correction for the OLDEST day: /compact was actually used in every session.
    ingest(client, [record(day=TODAY - timedelta(days=3), compact_uses=4)], admin_headers)
    after = query("SELECT date, efficiency_score FROM usage_metrics ORDER BY date")

    # The 7-day /compact term pools earlier days, so the later days' scores change too.
    assert all(a["efficiency_score"] > b["efficiency_score"] for a, b in zip(after, before, strict=True))


@pytest.mark.parametrize("bad, reason", [
    ({"input_tokens": -5}, "input_tokens"),
    ({"opus_pct": 0.9, "sonnet_pct": 0.9, "haiku_pct": 0.0}, "sum to 1"),
    ({"session_count": 2, "compact_uses": 3}, "compact_uses"),
    ({"date": (TODAY + timedelta(days=3)).isoformat()}, "future"),
    ({"date": "2026-02-30"}, "date"),
    ({"cache_reads": 10}, "cache_reads"),                          # typo'd field: not silently ignored
    ({"estimated_cost_usd": 0.01}, "computed by the server"),      # clients can't set cost
    ({"user_id": ""}, "user_id"),
])
def test_invalid_records_are_rejected_with_a_reason_and_the_rest_still_apply(client, admin_headers, query, bad,
                                                                             reason):
    response = ingest(client, [record(user="good"), record(user="bad", **bad)], admin_headers)

    body = response.json()
    assert response.status_code == 200 and body["inserted"] == 1
    assert len(body["rejected"]) == 1 and body["rejected"][0]["index"] == 1
    assert reason in " ".join(body["rejected"][0]["errors"])
    assert [r["user_id"] for r in query("SELECT user_id FROM usage_metrics")] == ["good"]


def test_unknown_engineer_without_a_name_is_rejected(client, admin_headers):
    rec = record(user="newbie")
    del rec["name"], rec["email"]

    body = ingest(client, [rec], admin_headers).json()

    assert body["inserted"] == 0 and "unknown engineer" in body["rejected"][0]["errors"][0]


def test_known_engineer_can_send_metrics_only(client, admin_headers):
    ingest(client, [record()], admin_headers)
    rec = record(day=TODAY - timedelta(days=2))
    del rec["name"], rec["email"]

    assert ingest(client, [rec], admin_headers).json()["inserted"] == 1


def test_duplicate_keys_within_one_batch_are_rejected(client, admin_headers):
    body = ingest(client, [record(), record(git_commits=9)], admin_headers).json()

    assert body["inserted"] == 1 and "duplicate" in body["rejected"][0]["errors"][0]


def test_oversized_batches_are_refused(client, admin_headers):
    response = ingest(client, [record(day=TODAY - timedelta(days=1 + i % 300), user=f"u{i}") for i in range(1001)],
                      admin_headers)
    assert response.status_code == 422


def test_ingested_data_shows_up_on_the_leaderboard(client, admin_headers):
    ingest(client, [record(user="a"), record(user="b", compact_uses=0, name="B", email="b@example.com")],
           admin_headers)

    board = client.get("/api/leaderboard").json()
    assert [r["user_id"] for r in board] == ["a", "b"]


def test_the_simulator_uses_the_same_ingestion_path(empty_db, query):
    from data.seed import generate_historical_data

    generate_historical_data(days_back=3, num_engineers=2)

    versions = {r["cost_price_version"] for r in query("SELECT cost_price_version FROM usage_metrics")}
    assert versions == {PRICE_TABLE_VERSION}
