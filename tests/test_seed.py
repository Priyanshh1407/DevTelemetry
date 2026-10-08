"""BUG-06: seeding is repeatable and resettable."""
from core.db import get_db_connection
from data.seed import generate_historical_data


def count(query, sql):
    return query(sql)[0]["n"]


def test_seeding_twice_does_not_duplicate_engineers(empty_db, query):
    generate_historical_data(days_back=3, num_engineers=10)
    generate_historical_data(days_back=3, num_engineers=10)

    assert count(query, "SELECT COUNT(*) AS n FROM engineers") == 10
    assert count(query, "SELECT COUNT(*) AS n FROM usage_metrics") == 30


def test_reset_replaces_existing_data(empty_db, query):
    conn = get_db_connection()
    conn.execute("INSERT INTO engineers (user_id, name, email) VALUES ('stale', 'Old Run', 'old@example.com')")
    conn.commit()
    conn.close()

    generate_historical_data(days_back=3, num_engineers=10, reset=True)

    assert count(query, "SELECT COUNT(*) AS n FROM engineers") == 10
    assert count(query, "SELECT COUNT(*) AS n FROM engineers WHERE user_id = 'stale'") == 0


def test_reset_keeps_alert_settings(empty_db, query):
    conn = get_db_connection()
    conn.execute("UPDATE alert_settings SET frequency = 'Daily', time = '08:00' WHERE id = 1")
    conn.commit()
    conn.close()

    generate_historical_data(days_back=2, num_engineers=3, reset=True)

    assert query("SELECT frequency, time FROM alert_settings") == [{"frequency": "Daily", "time": "08:00"}]


def test_same_seed_produces_identical_data(tmp_path, monkeypatch):
    def snapshot(name, seed):
        monkeypatch.setenv("DB_PATH", str(tmp_path / name))
        generate_historical_data(days_back=5, num_engineers=4, seed=seed)
        conn = get_db_connection()
        rows = [tuple(r) for r in conn.execute(
            "SELECT e.user_id, e.name, u.* FROM usage_metrics u JOIN engineers e USING (user_id) "
            "ORDER BY u.user_id, u.date")]
        conn.close()
        return rows

    assert snapshot("a.db", seed=7) == snapshot("b.db", seed=7)
    assert snapshot("c.db", seed=7) != snapshot("d.db", seed=8)


# ── ML-02: persona-based simulation ─────────────────────────────────────────

def _simulated_rows(query, days=30, engineers=10, seed=42):
    generate_historical_data(days_back=days, num_engineers=engineers, seed=seed,
                             end_date=__import__("datetime").date(2026, 3, 31))
    return query("SELECT * FROM usage_metrics ORDER BY date, user_id")


def bottom2_stability(rows):
    """Share of daily bottom-2 slots held by the two engineers with the lowest mean score."""
    from collections import defaultdict
    by_day, scores = defaultdict(list), defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
        scores[r["user_id"]].append(r["efficiency_score"])
    chronic = set(sorted(scores, key=lambda u: sum(scores[u]) / len(scores[u]))[:2])
    hits = sum(len({r["user_id"] for r in sorted(day, key=lambda r: r["efficiency_score"])[:2]} & chronic)
               for day in by_day.values())
    return hits / (2 * len(by_day))


def test_engineers_have_stable_habits(empty_db, query):
    # Chance level for 10 engineers is 0.20; the old i.i.d. generator scored 0.24 (seeds 1-5).
    # Personas (ML-02) reached 0.71; pooling the /compact term over 7 days (ML-03b) took the
    # 30-seed median from 0.65 to 0.82 (worst seed 0.33 -> 0.60). Averaged over seeds so the
    # assertion is about the model, not one lucky draw.
    from core.db import get_db_connection

    values = []
    for seed in range(1, 6):
        conn = get_db_connection()
        conn.execute("DELETE FROM usage_metrics")
        conn.execute("DELETE FROM engineers")
        conn.commit()
        conn.close()
        values.append(bottom2_stability(_simulated_rows(query, seed=seed)))
    mean = sum(values) / len(values)
    print(f"bottom-2 stability per seed: {[round(v, 2) for v in values]}, mean {mean:.2f}")
    assert mean >= 0.75
    assert min(values) >= 0.60  # every seed well above chance and the old generator


def test_weekday_cost_matches_published_claude_code_benchmark(empty_db, query):
    # https://code.claude.com/docs/en/costs: ~$13 per developer per active day on average,
    # below $30 per active day for 90% of users.
    from datetime import date
    rows = _simulated_rows(query, days=60, engineers=20)
    weekday_costs = sorted(r["estimated_cost_usd"] for r in rows if date.fromisoformat(r["date"]).weekday() < 5)
    mean = sum(weekday_costs) / len(weekday_costs)
    p90 = weekday_costs[int(0.9 * len(weekday_costs))]
    print(f"weekday cost mean ${mean:.2f}, p90 ${p90:.2f}")
    assert 9 <= mean <= 17
    assert p90 < 30


def test_simulated_rows_are_internally_consistent(empty_db, query):
    for r in _simulated_rows(query):
        # Anthropic semantics: three separate, non-negative parts of the prompt
        assert min(r["input_tokens"], r["cache_read_tokens"], r["cache_write_tokens"]) >= 0
        assert r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"] > 0
        assert abs(r["opus_pct"] + r["sonnet_pct"] + r["haiku_pct"] - 1.0) <= 0.011
        assert 0 <= r["compact_uses"] <= r["session_count"]
        assert r["session_count"] >= 1
        assert min(r["output_tokens"], r["cache_write_tokens"], r["git_commits"]) >= 0
        assert 0 <= r["efficiency_score"] <= 100


# ── DX-01: container start seeds only an empty database ─────────────────────

def test_if_empty_seeds_an_empty_database(empty_db, query):
    from data.seed import main

    main(["--if-empty", "--days", "3", "--engineers", "4"])

    assert count(query, "SELECT COUNT(*) AS n FROM engineers") == 4


def test_if_empty_leaves_existing_data_alone(empty_db, query):
    from data.seed import main

    main(["--days", "3", "--engineers", "4", "--seed", "1"])
    before = query("SELECT * FROM usage_metrics ORDER BY id")

    main(["--if-empty", "--days", "5", "--engineers", "10", "--seed", "2"])

    assert query("SELECT * FROM usage_metrics ORDER BY id") == before
