from datetime import UTC, datetime, timedelta

import pytest

from tony.core.automation.occurrences import LATE_LIMIT, occurrences
from tony.core.automation.routine import ALL_WEEKDAYS, Routine

MADRID = "Europe/Madrid"
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)
MONDAY_START = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def routine(time="08:30", weekdays=ALL_WEEKDAYS, tz="UTC", active_since=LONG_AGO, rid=7):
    return Routine(
        id=rid,
        name="r",
        prompt="p",
        time=time,
        weekdays=weekdays,
        timezone=tz,
        enabled=True,
        active_since=active_since,
    )


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def ids(found):
    return [item.id for item in found]


def test_due_once_local_time_has_passed():
    found = occurrences(routine(), utc(2026, 11, 2, 8, 31))

    assert ids(found) == ["7:2026-11-02:08:30"]
    assert found[0].scheduled_for == utc(2026, 11, 2, 8, 30)


def test_not_due_before_local_time():
    assert occurrences(routine(active_since=MONDAY_START), utc(2026, 11, 2, 8, 29)) == []


def test_due_exactly_at_the_time():
    found = occurrences(routine(active_since=MONDAY_START), utc(2026, 11, 2, 8, 30))

    assert ids(found) == ["7:2026-11-02:08:30"]


MONDAY_ONLY = 1


def test_weekday_mask_selected_and_unselected():
    monday = occurrences(routine(weekdays=MONDAY_ONLY), utc(2026, 11, 2, 8, 31))
    tuesday = occurrences(routine(weekdays=MONDAY_ONLY), utc(2026, 11, 3, 8, 31))

    assert ids(monday) == ["7:2026-11-02:08:30"]
    assert tuesday == []


def test_sunday_is_bit_six():
    sunday = occurrences(routine(weekdays=1 << 6), utc(2026, 11, 1, 9, 0))

    assert ids(sunday) == ["7:2026-11-01:08:30"]


def test_active_since_floor_prevents_backfill():
    since = utc(2026, 11, 2, 9, 0)

    assert occurrences(routine(active_since=since), utc(2026, 11, 2, 10, 0)) == []
    assert ids(occurrences(routine(active_since=since), utc(2026, 11, 3, 8, 31))) == [
        "7:2026-11-03:08:30"
    ]


def test_late_boundary_is_twelve_hours_inclusive():
    found = occurrences(routine(), utc(2026, 11, 2, 8, 30))[-1]

    assert LATE_LIMIT == timedelta(hours=12)
    assert not found.expired(utc(2026, 11, 2, 20, 30))
    assert found.expired(utc(2026, 11, 2, 20, 30, 1))


def test_occurrences_up_to_a_day_late_are_reported_so_they_can_be_skipped():
    assert ids(occurrences(routine(), utc(2026, 11, 3, 8, 29))) == ["7:2026-11-02:08:30"]
    assert ids(occurrences(routine(), utc(2026, 11, 3, 8, 30))) == [
        "7:2026-11-02:08:30",
        "7:2026-11-03:08:30",
    ]


def test_older_than_a_day_is_ignored():
    found = occurrences(routine(), utc(2026, 11, 4, 8, 29))

    assert ids(found) == ["7:2026-11-03:08:30"]


def test_id_uses_local_date_and_time_in_the_zone():
    # 23:30 in Madrid (UTC+1) on Nov 2 is 22:30 UTC.
    found = occurrences(routine(time="23:30", tz=MADRID), utc(2026, 11, 2, 22, 31))

    assert ids(found) == ["7:2026-11-02:23:30"]
    assert found[0].scheduled_for == utc(2026, 11, 2, 22, 30)


def test_negative_offset_zone_crosses_the_utc_date():
    # 20:00 in New York (UTC-5 in November) is 01:00 UTC the next day.
    found = occurrences(routine(time="20:00", tz="America/New_York"), utc(2026, 11, 3, 1, 5))

    assert ids(found) == ["7:2026-11-02:20:00"]
    assert found[0].scheduled_for == utc(2026, 11, 3, 1, 0)


def test_spring_forward_gap_runs_once_after_the_change():
    # Madrid 2026-03-29: 02:00 -> 03:00; 02:30 does not exist.
    zone_args = {"time": "02:30", "tz": MADRID}
    before = occurrences(routine(**zone_args), utc(2026, 3, 29, 1, 29))
    after = occurrences(routine(**zone_args), utc(2026, 3, 29, 1, 31))
    later = occurrences(routine(**zone_args), utc(2026, 3, 29, 6, 0))

    assert [i for i in ids(before) if "03-29" in i] == []
    assert ids(after) == ["7:2026-03-29:02:30"]
    assert after[0].scheduled_for == utc(2026, 3, 29, 1, 30)
    assert [i for i in ids(later) if "03-29" in i] == ["7:2026-03-29:02:30"]


def test_fall_back_repeat_runs_once_for_the_date():
    # Madrid 2026-10-25: 03:00 -> 02:00; 02:30 happens twice (00:30 UTC and 01:30 UTC).
    zone_args = {"time": "02:30", "tz": MADRID}
    first = occurrences(routine(**zone_args), utc(2026, 10, 25, 0, 31))
    second_pass = occurrences(routine(**zone_args), utc(2026, 10, 25, 1, 31))

    assert [i for i in ids(first) if "10-25" in i] == ["7:2026-10-25:02:30"]
    assert first[-1].scheduled_for == utc(2026, 10, 25, 0, 30)
    assert [i for i in ids(second_pass) if "10-25" in i] == ["7:2026-10-25:02:30"]


@pytest.mark.parametrize("hour", [0, 23])
def test_midnight_neighbours_get_their_own_local_date(hour):
    found = occurrences(routine(time=f"{hour:02d}:00"), utc(2026, 11, 2, 23, 59))

    assert ids(found)[-1] == f"7:2026-11-02:{hour:02d}:00"


def test_occurrence_at_exactly_active_since_is_due():
    since = utc(2026, 11, 2, 8, 30)

    assert ids(occurrences(routine(active_since=since), utc(2026, 11, 2, 9, 0))) == [
        "7:2026-11-02:08:30"
    ]
