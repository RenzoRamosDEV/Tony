from datetime import UTC, datetime, timedelta

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import HANG, FakeConfirmer
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.core.automation.launcher import routine_runner
from tony.core.automation.scheduler import RoutineScheduler
from tony.core.automation.store import RoutineStore
from tony.core.orchestrator.runner import RunDeps

CONFIRM_FAST = (
    "default: confirm\nrules: []\nlimits: {confirm_timeout_s: 0.05}\n"
    "auth: {pin_required: false, lock_after_min: 30}\n"
)
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
DONE = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}


async def test_unanswered_confirmation_denies_the_action_and_the_run_is_recorded(tmp_path):
    home, notes = make_viernes_home(tmp_path, policy=CONFIRM_FAST)
    confirmer = FakeConfirmer([HANG])
    engine = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"}), Final(structured=DONE)]
    )
    deps = RunDeps(root=home, engine=engine, environ={}, confirmer=confirmer)
    store = RoutineStore(home, clock=lambda: NOW - timedelta(hours=2))
    store.add(name="r", prompt="borra", time="08:30", weekdays=None, timezone="UTC")
    store.close()
    store = RoutineStore(home, clock=lambda: NOW)
    scheduler = RoutineScheduler(
        store, routine_runner(deps, "viernes"), unlocked=lambda: True, clock=lambda: NOW
    )

    await scheduler.tick()

    assert len(confirmer.requests) == 1
    assert (notes / "a.md").exists()
    assert "not confirmed by the user (timeout)" in engine.replies[0].text
    (run,) = store.runs()
    assert run.status == "error" and run.result
    store.close()
