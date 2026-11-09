from tony.core.automation.routine import Routine
from tony.core.automation.scheduler import RoutineRunner, RunOutcome
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.runner import RunDeps, run_task


def routine_runner(deps: RunDeps, worker_name: str) -> RoutineRunner:
    """Runs a routine's prompt as the objective of a guarded worker task."""

    async def run(routine: Routine) -> RunOutcome:
        request = TaskRequest(objetivo=routine.prompt)
        result = await run_task(worker_name, request, deps, origin="routine")
        if result.errores:
            return RunOutcome(ok=False, text="\n".join(result.errores))
        return RunOutcome(ok=True, text=result.resumen)

    return run
