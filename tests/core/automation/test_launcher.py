import json
from datetime import UTC, datetime

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import FakeModelEngine, Final
from tony.core.automation.launcher import routine_runner
from tony.core.automation.routine import ALL_WEEKDAYS, Routine
from tony.core.orchestrator.runner import RunDeps

ROUTINE = Routine(
    1, "r", "resume mis notas", "08:30", ALL_WEEKDAYS, "UTC", True, datetime(2026, 1, 1, tzinfo=UTC)
)
OK = {"resumen": "todo bien", "datos": None, "pasos": [], "errores": []}


def first_log_event(home):
    (path,) = (home / "logs" / "tasks").glob("*.jsonl")
    return json.loads(path.read_text().splitlines()[0])


async def test_runs_the_prompt_as_a_routine_task(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    engine = FakeModelEngine([Final(structured=OK)])
    run = routine_runner(RunDeps(root=home, engine=engine, environ={}), "viernes")

    outcome = await run(ROUTINE)

    assert outcome.ok and outcome.text == "todo bien"
    assert engine.request.objetivo == "resume mis notas"
    event = first_log_event(home)
    assert event["origin"] == "routine" and event["agent"] == "viernes"


async def test_task_errors_make_the_outcome_an_error(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    failed = {"resumen": "", "datos": None, "pasos": [], "errores": ["no pude", "otra"]}
    engine = FakeModelEngine([Final(structured=failed)])
    run = routine_runner(RunDeps(root=home, engine=engine, environ={}), "viernes")

    outcome = await run(ROUTINE)

    assert not outcome.ok and outcome.text == "no pude\notra"
