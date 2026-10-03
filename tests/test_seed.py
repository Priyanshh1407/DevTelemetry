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
    conn.execute("INSERT INTO engineers (user_id, name, email) VALUES ('stale', 'Old Run', 'old@company.com')")
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
