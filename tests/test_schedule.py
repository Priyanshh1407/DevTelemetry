"""ARCH-02: deciding whether a scheduled alert slot is due."""
from datetime import datetime, timedelta, timezone

import pytest

from core.schedule import due_slot

UTC = timezone.utc
GRACE = timedelta(hours=2)


def at(*args):
    return datetime(*args, tzinfo=UTC)


# 2026-10-02 is a Friday. 17:00 in Asia/Kolkata (UTC+5:30) is 11:30 UTC.

def test_weekly_slot_is_due_at_its_local_time():
    slot = due_slot("Weekly", "Friday", "17:00", "Asia/Kolkata", now_utc=at(2026, 10, 2, 11, 30), grace=GRACE)
    assert slot == at(2026, 10, 2, 11, 30)


def test_slot_stays_due_through_the_grace_window_for_late_cron_runs():
    assert due_slot("Weekly", "Friday", "17:00", "Asia/Kolkata", now_utc=at(2026, 10, 2, 13, 25),
                    grace=GRACE) == at(2026, 10, 2, 11, 30)


def test_slot_is_not_sent_when_it_is_older_than_the_grace_window():
    # e.g. the service was down for hours: don't send Friday's alerts on Friday night.
    assert due_slot("Weekly", "Friday", "17:00", "Asia/Kolkata", now_utc=at(2026, 10, 2, 13, 31),
                    grace=GRACE) is None


def test_not_due_before_the_scheduled_time():
    assert due_slot("Weekly", "Friday", "17:00", "Asia/Kolkata", now_utc=at(2026, 10, 2, 11, 29),
                    grace=GRACE) is None


def test_weekly_slot_is_not_due_on_other_days():
    assert due_slot("Weekly", "Friday", "17:00", "Asia/Kolkata", now_utc=at(2026, 10, 1, 11, 30),
                    grace=GRACE) is None


def test_timezone_matters():
    # 17:00 UTC is not 17:00 in Kolkata.
    assert due_slot("Weekly", "Friday", "17:00", "UTC", now_utc=at(2026, 10, 2, 11, 30), grace=GRACE) is None
    assert due_slot("Weekly", "Friday", "17:00", "UTC", now_utc=at(2026, 10, 2, 17, 5),
                    grace=GRACE) == at(2026, 10, 2, 17, 0)


def test_daily_slot_is_due_every_day():
    for day in range(1, 8):
        assert due_slot("Daily", "Monday", "09:00", "UTC", now_utc=at(2026, 10, day, 9, 10),
                        grace=GRACE) == at(2026, 10, day, 9, 0)


def test_daily_slot_just_after_midnight_local_uses_the_previous_local_day():
    # 23:30 New York time on Oct 1 is 03:30 UTC on Oct 2.
    assert due_slot("Daily", "Monday", "23:30", "America/New_York", now_utc=at(2026, 10, 2, 4, 0),
                    grace=GRACE) == at(2026, 10, 2, 3, 30)


def test_daylight_saving_shift_moves_the_utc_time_not_the_local_time():
    # US DST ends 2026-11-01: 09:00 New York is 13:00 UTC before, 14:00 UTC after.
    assert due_slot("Daily", "Monday", "09:00", "America/New_York", now_utc=at(2026, 10, 30, 13, 5),
                    grace=GRACE) == at(2026, 10, 30, 13, 0)
    assert due_slot("Daily", "Monday", "09:00", "America/New_York", now_utc=at(2026, 11, 2, 14, 5),
                    grace=GRACE) == at(2026, 11, 2, 14, 0)


def test_requires_an_aware_utc_now():
    with pytest.raises(ValueError):
        due_slot("Daily", "Monday", "09:00", "UTC", now_utc=datetime(2026, 10, 2, 9, 0), grace=GRACE)
