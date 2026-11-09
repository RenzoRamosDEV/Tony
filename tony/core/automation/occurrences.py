from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from tony.core.automation.routine import Routine

LATE_LIMIT = timedelta(hours=12)
RECORD_WINDOW = timedelta(hours=24)
"""Occurrences later than this are forgotten instead of recorded as skipped."""


def is_expired(scheduled_for: datetime, now: datetime) -> bool:
    return now - scheduled_for > LATE_LIMIT


@dataclass(frozen=True)
class Occurrence:
    id: str
    scheduled_for: datetime

    def expired(self, now: datetime) -> bool:
        return is_expired(self.scheduled_for, now)


def occurrences(routine: Routine, now: datetime) -> list[Occurrence]:
    """Occurrences of the routine that are due at `now`, oldest first.

    The id carries the configured local date and time, so a clock change never produces two
    ids for one date; the instant is the first of the wall times that match (`fold=0`).
    """
    zone = routine.zone
    today = now.astimezone(zone).date()
    hour, minute = (int(part) for part in routine.time.split(":"))
    found = []
    for day in (today - timedelta(days=1), today):
        if not routine.weekdays & (1 << day.weekday()):
            continue
        instant = _instant(day, hour, minute, zone)
        if routine.active_since <= instant <= now and now - instant <= RECORD_WINDOW:
            found.append(Occurrence(f"{routine.id}:{day.isoformat()}:{routine.time}", instant))
    return found


def _instant(day: date, hour: int, minute: int, zone) -> datetime:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
    return local.astimezone(UTC)
