import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from tony.core.automation.launcher import routine_runner
from tony.core.automation.scheduler import ROUTINES_SOURCE, RoutineScheduler
from tony.core.automation.store import RoutineStore
from tony.core.config.placeholders import SecretMasker
from tony.core.events import core_events
from tony.core.events.core_events import Publisher
from tony.core.orchestrator.runner import RunDeps


@dataclass
class RunningScheduler:
    task: "asyncio.Task[None]"
    store: RoutineStore

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.store.close()


def start_scheduler(
    deps: RunDeps,
    *,
    worker: str,
    unlocked: Callable[[], bool],
    masker: SecretMasker,
    publish: Publisher,
) -> RunningScheduler | None:
    """Run the routine scheduler in the current event loop.

    `deps` are the dependencies of the routine tasks themselves. A routines database that
    cannot be opened is published as an `error` and leaves the host running without routines.
    """
    try:
        store = RoutineStore(deps.root, clock=deps.clock, masker=masker)
    except sqlite3.Error as error:
        publish(core_events.error(ROUTINES_SOURCE, f"routines unavailable: {error}"))
        return None
    scheduler = RoutineScheduler(
        store,
        routine_runner(deps, worker),
        unlocked=unlocked,
        clock=deps.clock,
        publish=publish,
    )
    return RunningScheduler(asyncio.create_task(scheduler.run_forever()), store)
