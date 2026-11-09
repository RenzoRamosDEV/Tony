import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from tony.core.automation.occurrences import is_expired, occurrences
from tony.core.automation.routine import Routine
from tony.core.automation.store import RoutineStore, RunRecord
from tony.core.events import core_events
from tony.core.events.core_events import Publisher
from tony.core.logging.task_log import Clock, utc_now

ROUTINES_SOURCE = "routines"
STALE_CLAIM = timedelta(seconds=600)


@dataclass(frozen=True)
class RunOutcome:
    ok: bool
    text: str


RoutineRunner = Callable[[Routine], Awaitable[RunOutcome]]


class RoutineScheduler:
    """Turns due occurrences into guarded task runs; it never prompts for a PIN.

    `tick()` does one pass and is driven by `run_forever()` every `interval_s` seconds.
    """

    def __init__(
        self,
        store: RoutineStore,
        run: RoutineRunner,
        *,
        unlocked: Callable[[], bool],
        clock: Clock = utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = 30,
        publish: Publisher = core_events.no_op,
    ) -> None:
        self._store = store
        self._run = run
        self._unlocked = unlocked
        self._clock = clock
        self._sleep = sleep
        self._interval_s = interval_s
        self._publish = publish

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as error:
                self._report(f"routine scheduler tick failed: {error}")
            await self._sleep(self._interval_s)

    async def tick(self) -> None:
        self._store.interrupt_stale(STALE_CLAIM)
        self._record_due_occurrences()
        for run in self._store.queued():
            if not self._unlocked():
                return
            await self._start(run)

    def _record_due_occurrences(self) -> None:
        now = self._clock()
        for routine in self._store.routines():
            if not routine.enabled:
                continue
            try:
                due = occurrences(routine, now)
            except Exception as error:
                self._report(f"routine {routine.name} cannot be scheduled: {error}")
                continue
            for occurrence in due:
                status = "skipped" if occurrence.expired(now) else "queued"
                self._store.record(routine.id, occurrence, status)

    async def _start(self, run: RunRecord) -> None:
        if is_expired(run.scheduled_for, self._clock()):
            self._store.skip(run.occurrence_id)
            return
        routine = self._store.get(run.routine_id)
        if routine is None or not routine.enabled:
            self._store.skip(run.occurrence_id)
            return
        if not self._store.claim(run.occurrence_id):
            return
        try:
            outcome = await self._run(routine)
        except Exception as error:
            self._report(f"routine {routine.name} failed: {error}")
            self._store.finish(run.occurrence_id, "error", str(error))
            return
        self._store.finish(run.occurrence_id, "ok" if outcome.ok else "error", outcome.text)

    def _report(self, message: str) -> None:
        self._publish(core_events.error(ROUTINES_SOURCE, message, clock=self._clock))
