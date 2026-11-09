from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ALL_WEEKDAYS = (1 << len(WEEKDAY_NAMES)) - 1


class RoutineError(ValueError):
    pass


@dataclass(frozen=True)
class Routine:
    id: int
    name: str
    prompt: str
    time: str
    weekdays: int
    timezone: str
    enabled: bool
    active_since: datetime
    """UTC instant before which no occurrence is run (set on add and on enable)."""

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def parse_time(text: str) -> str:
    try:
        parsed = datetime.strptime(text.strip(), "%H:%M")
    except ValueError as error:
        raise RoutineError(f"invalid time '{text}'; use HH:MM") from error
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def parse_weekdays(text: str) -> int:
    mask = 0
    for part in text.split(","):
        name = part.strip().lower()
        if name not in WEEKDAY_NAMES:
            raise RoutineError(f"invalid weekday '{part.strip()}'; use {','.join(WEEKDAY_NAMES)}")
        mask |= 1 << WEEKDAY_NAMES.index(name)
    return mask


def format_weekdays(mask: int) -> str:
    if mask == ALL_WEEKDAYS:
        return "daily"
    return ",".join(name for index, name in enumerate(WEEKDAY_NAMES) if mask & (1 << index))


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (KeyError, ValueError, OSError) as error:
        raise RoutineError(f"unknown timezone '{name}'") from error
    return name
