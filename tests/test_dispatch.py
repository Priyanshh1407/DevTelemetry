"""PERF-02 / ARCH-02 foundation: the dispatch_runs ledger."""
from datetime import datetime, timedelta, timezone

import pytest

from core.dispatch import (DispatchBusy, DispatchCoolingDown, SlotAlreadyDispatched, finish_run, get_run,
                           start_run)

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
SUMMARY = {"engineers": 1, "developer_emails": {"sent": 1, "failed": 0, "skipped": 0},
           "failed_recipients": [], "manager_digest": "sent", "slack": "skipped"}


def test_only_one_run_at_a_time(empty_db):
    start_run("manual", now=T0)
    with pytest.raises(DispatchBusy):
        start_run("manual", now=T0)
    with pytest.raises(DispatchBusy):
        start_run("schedule", slot="2026-10-02T11:30:00+00:00", now=T0)


def test_finished_run_frees_the_slot_for_the_next(empty_db):
    run_id = start_run("manual", now=T0)
    finish_run(run_id, "success", SUMMARY, now=T0 + timedelta(seconds=5))

    assert start_run("manual", now=T0 + timedelta(hours=1)) != run_id


def test_stale_running_row_is_abandoned_instead_of_blocking_forever(empty_db):
    crashed = start_run("manual", now=T0)  # process died before finish_run

    new = start_run("manual", now=T0 + timedelta(minutes=20))

    assert get_run(crashed)["status"] == "abandoned"
    assert get_run(new)["status"] == "running"


def test_cooldown_after_a_delivering_run(empty_db):
    run_id = start_run("manual", now=T0)
    finish_run(run_id, "success", SUMMARY, now=T0)

    with pytest.raises(DispatchCoolingDown) as info:
        start_run("manual", cooldown_seconds=300, now=T0 + timedelta(seconds=10))
    assert info.value.retry_after == 290
    start_run("manual", cooldown_seconds=300, now=T0 + timedelta(seconds=301))


@pytest.mark.parametrize("status", ["skipped", "no_data", "error"])
def test_runs_that_delivered_nothing_do_not_start_the_cooldown(empty_db, status):
    run_id = start_run("manual", now=T0)
    finish_run(run_id, status, None, now=T0)

    start_run("manual", cooldown_seconds=300, now=T0 + timedelta(seconds=1))


def test_each_scheduled_slot_runs_at_most_once(empty_db):
    slot = "2026-10-02T11:30:00+00:00"
    run_id = start_run("schedule", slot=slot, now=T0)
    finish_run(run_id, "failed", SUMMARY, now=T0)

    with pytest.raises(SlotAlreadyDispatched):
        start_run("schedule", slot=slot, now=T0 + timedelta(minutes=15))
    start_run("schedule", slot="2026-10-09T11:30:00+00:00", now=T0 + timedelta(days=7))


def test_get_run_returns_parsed_summary(empty_db):
    run_id = start_run("manual", now=T0)
    finish_run(run_id, "success", SUMMARY, now=T0 + timedelta(seconds=3))

    run = get_run(run_id)

    assert run["summary"] == SUMMARY
    assert run["status"] == "success" and run["trigger"] == "manual"
    assert get_run(9999) is None


def test_concurrent_starts_from_many_threads_admit_exactly_one(empty_db):
    import threading

    barrier, results = threading.Barrier(8), []

    def attempt():
        barrier.wait()
        try:
            results.append(start_run("manual", now=T0))
        except DispatchBusy:
            results.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("busy") == 7
