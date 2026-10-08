"""UPG-05: the simulator can coach engineers with a known true effect (the ground truth that
core/impact.py is validated against)."""
import random
from datetime import date

import pytest

from data.seed import (COACHING_EVERY_DAYS, FULL_EFFECT, apply_coaching, generate_historical_data,
                       make_persona)

END = date(2026, 3, 31)


def usage(query):
    return query("SELECT user_id, date, input_tokens, cache_read_tokens, opus_pct, compact_uses "
                 "FROM usage_metrics ORDER BY date, user_id")


def test_no_coaching_by_default(empty_db, query):
    generate_historical_data(days_back=40, num_engineers=10, end_date=END)
    assert query("SELECT COUNT(*) AS n FROM coaching_events")[0]["n"] == 0


def test_coaching_with_no_effect_records_events_but_leaves_the_data_unchanged(tmp_path, monkeypatch, query):
    from core.db import get_db_connection

    def run(name, effect):
        monkeypatch.setenv("DB_PATH", str(tmp_path / name))
        generate_historical_data(days_back=40, num_engineers=10, end_date=END, coaching_effect=effect)
        conn = get_db_connection()
        rows = [tuple(r) for r in conn.execute("SELECT * FROM usage_metrics ORDER BY date, user_id")]
        events = [dict(r) for r in conn.execute("SELECT * FROM coaching_events ORDER BY coached_on, user_id")]
        conn.close()
        return rows, events

    plain, no_events = run("a.db", None)
    null, events = run("b.db", "none")

    assert plain == null and no_events == []
    # Every 14th day the two critical engineers are coached on their weakest area.
    assert len(events) == 2 * (40 // COACHING_EVERY_DAYS)
    assert {e["source"] for e in events} == {"simulated"}
    assert {e["severity"] for e in events} == {"critical"}
    assert {e["target_area"] for e in events} <= {"cache", "model_mix", "discipline"}


def test_coached_engineers_are_the_bottom_two_on_that_day(empty_db, query):
    generate_historical_data(days_back=30, num_engineers=10, end_date=END, coaching_effect="none")
    for e in query("SELECT * FROM coaching_events"):
        day = query("SELECT user_id FROM usage_metrics WHERE date = ? ORDER BY efficiency_score",
                    (e["coached_on"],))
        assert e["user_id"] in {r["user_id"] for r in day[:2]}


def test_a_real_effect_changes_the_data_only_after_the_first_coaching(tmp_path, monkeypatch):
    from core.db import get_db_connection

    def rows(name, effect):
        monkeypatch.setenv("DB_PATH", str(tmp_path / name))
        generate_historical_data(days_back=40, num_engineers=10, end_date=END, coaching_effect=effect)
        conn = get_db_connection()
        out = {(r["user_id"], r["date"]): tuple(r) for r in conn.execute(
            "SELECT user_id, date, input_tokens, cache_read_tokens, opus_pct, compact_uses FROM usage_metrics")}
        first = conn.execute("SELECT MIN(coached_on) FROM coaching_events").fetchone()[0]
        conn.close()
        return out, first

    null, first = rows("a.db", "none")
    real, _ = rows("b.db", "moderate")

    assert all(null[k] == real[k] for k in null if k[1] <= first)
    assert any(null[k] != real[k] for k in null if k[1] > first)


def test_reset_removes_coaching_events(empty_db, query):
    generate_historical_data(days_back=30, num_engineers=10, end_date=END, coaching_effect="none")
    generate_historical_data(days_back=3, num_engineers=10, end_date=END, reset=True)
    assert query("SELECT COUNT(*) AS n FROM coaching_events")[0]["n"] == 0


class Always:
    """An rng whose adherence draw always says yes (or always no)."""
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


@pytest.mark.parametrize("area, key, sign", [("cache", "cache_hit", 1), ("model_mix", "opus_share", -1),
                                             ("discipline", "compact_rate", 1)])
def test_coaching_moves_the_targeted_habit_by_the_true_effect(area, key, sign):
    persona = {**make_persona(random.Random(3)), "cache_hit": 0.5, "opus_share": 0.4, "compact_rate": 0.3}

    adhered = apply_coaching(persona, area, "moderate", Always(0.0))
    ignored = apply_coaching(persona, area, "moderate", Always(0.99))
    small = apply_coaching(persona, area, "small", Always(0.0))

    assert adhered[key] == pytest.approx(persona[key] + sign * FULL_EFFECT[area])
    assert small[key] == pytest.approx(persona[key] + sign * FULL_EFFECT[area] / 2)
    assert ignored == persona
    assert {k: v for k, v in adhered.items() if k != key} == {k: v for k, v in persona.items() if k != key}
    assert persona["cache_hit"] == 0.5          # the input persona is not modified


def test_habits_stay_in_range():
    persona = {**make_persona(random.Random(3)), "cache_hit": 0.94, "opus_share": 0.05, "compact_rate": 0.9}
    assert apply_coaching(persona, "cache", "moderate", Always(0.0))["cache_hit"] <= 0.95
    assert apply_coaching(persona, "model_mix", "moderate", Always(0.0))["opus_share"] >= 0.02
    assert apply_coaching(persona, "discipline", "moderate", Always(0.0))["compact_rate"] <= 0.95
