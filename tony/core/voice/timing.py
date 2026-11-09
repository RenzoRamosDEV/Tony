import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count

MARKS = (
    "speech_end",
    "capture_close",
    "stt_start",
    "stt_end",
    "first_token",
    "synthesis_start",
    "synthesis_end",
    "playback_start",
)
INTERVALS = {
    "endpointing": ("speech_end", "capture_close"),
    "transcription": ("capture_close", "stt_end"),
    "reply_start": ("stt_end", "first_token"),
    "first_token_to_playback": ("first_token", "playback_start"),
    "end_to_end": ("speech_end", "playback_start"),
}
MIN_SAMPLES_FOR_P95 = 20
LAG_INTERVAL_S = 0.01
_MS = 1000.0


class NullTimings:
    """The default recorder: every call is a no-op."""

    def now(self) -> float:
        return 0.0

    def begin_turn(self) -> int | None:
        return None

    def mark(self, turn: int | None, name: str, at: float | None = None) -> None:
        return None

    def turns(self) -> dict[int, dict[str, float]]:
        return {}


class StageTimings:
    """Thread-safe recorder of monotonic stage timestamps per voice turn. It stores only turn
    ids, mark names and numbers; the first mark of a name in a turn wins."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._ids = count(1)
        self._turns: dict[int, dict[str, float]] = {}

    def now(self) -> float:
        return self._clock()

    def begin_turn(self) -> int:
        with self._lock:
            turn = next(self._ids)
            self._turns[turn] = {}
            return turn

    def mark(self, turn: int | None, name: str, at: float | None = None) -> None:
        if turn is None:
            return
        if name not in MARKS:
            raise ValueError(f"unknown mark '{name}'")
        if at is not None and not isinstance(at, int | float):
            raise TypeError("a mark timestamp must be a number")
        timestamp = self._clock() if at is None else float(at)
        with self._lock:
            self._turns[turn].setdefault(name, timestamp)

    def turns(self) -> dict[int, dict[str, float]]:
        with self._lock:
            return {turn: dict(marks) for turn, marks in self._turns.items()}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = fraction * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


@dataclass(frozen=True)
class IntervalStat:
    p50: float
    p95: float | None


@dataclass(frozen=True)
class Cohort:
    count: int
    intervals: dict[str, IntervalStat] = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    cold: Cohort
    warm: Cohort


def summarise(timings: NullTimings | StageTimings) -> Report:
    completed = sorted(
        (
            marks
            for marks in timings.turns().values()
            if "speech_end" in marks and "playback_start" in marks
        ),
        key=lambda marks: marks["speech_end"],
    )
    return Report(_cohort(completed[:1]), _cohort(completed[1:]))


def _cohort(turns: list[dict[str, float]]) -> Cohort:
    intervals: dict[str, IntervalStat] = {}
    for name, (start, end) in INTERVALS.items():
        durations = [t[end] - t[start] for t in turns if start in t and end in t]
        if durations:
            enough = len(durations) >= MIN_SAMPLES_FOR_P95
            p95 = percentile(durations, 0.95) if enough else None
            intervals[name] = IntervalStat(percentile(durations, 0.5) or 0.0, p95)
    return Cohort(len(turns), intervals)


def format_report(report: Report, lag: "LoopLagSampler | None" = None) -> str:
    lines: list[str] = []
    for label, cohort in (("cold", report.cold), ("warm", report.warm)):
        lines.append(f"{label} (n={cohort.count})")
        for name, stat in cohort.intervals.items():
            p95 = "n/a" if stat.p95 is None else f"{stat.p95:.3f} s"
            lines.append(f"  {name}: p50 {stat.p50:.3f} s, p95 {p95}")
    if lag is not None:
        lines.append(f"loop lag: max {lag.max_ms:.1f} ms, p95 {lag.p95_ms:.1f} ms")
    return "\n".join(lines)


class LoopLagSampler:
    """Measures how late a 10 ms timer fires on the running event loop."""

    def __init__(self, interval_s: float = LAG_INTERVAL_S) -> None:
        self._interval_s = interval_s
        self._lags_ms: list[float] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def max_ms(self) -> float:
        return max(self._lags_ms, default=0.0)

    @property
    def p95_ms(self) -> float:
        return percentile(self._lags_ms, 0.95) or 0.0

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            expected = loop.time() + self._interval_s
            await asyncio.sleep(self._interval_s)
            self._lags_ms.append(max(0.0, loop.time() - expected) * _MS)
