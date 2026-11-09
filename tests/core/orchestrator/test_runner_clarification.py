import asyncio
from datetime import UTC, datetime

import pytest

from tests.core.orchestrator.skills_home import set_native
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.clarify import HANG, FakeClarifier
from tests.fakes.confirm import FakeConfirmer
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.core.clarification.port import NoChannelClarifier
from tony.core.config.settings import load_config
from tony.core.events.messages import TaskRequest
from tony.core.loader.agent import load_agent
from tony.core.orchestrator.runner import RunDeps, _ask_user, _prepare_run, run_task
from tony.core.orchestrator.supervisor import USER_CANCELLED

TASK_ID = "c" * 32
REQUEST = TaskRequest(objetivo="Manda el correo")
OK = {"resumen": "ok", "datos": None, "pasos": [], "errores": []}
ASK = CallTool("tony.ask_user", {"question": "¿Qué cuenta?", "options": ["Personal", "Trabajo"]})
DELETE = CallTool("filesystem.delete_file", {"path": "a.md"})
READ = CallTool("filesystem.read_file", {"path": "a.md"})
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

POLICY = """\
default: confirm
rules:
- match: filesystem.read_*
  verdict: allow
- match: tony.ask_user
  verdict: allow
limits:
  tool_timeout_s: {tool}
  confirm_timeout_s: {confirm}
"""


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def make_home(tmp_path, *, tool=20, confirm=60):
    home, notes = make_viernes_home(tmp_path, policy=POLICY.format(tool=tool, confirm=confirm))
    set_native(home, "viernes", ["ask_user"])
    return home, notes


def deps_for(home, engine, **options):
    return RunDeps(
        root=home,
        engine=engine,
        environ={},
        task_id_factory=lambda: TASK_ID,
        clock=lambda: FIXED,
        **options,
    )


async def run(home, steps, **options):
    engine = FakeModelEngine([*steps, Final(structured=OK)])
    result = await run_task("viernes", REQUEST, deps_for(home, engine, **options))
    return engine, result


async def test_answer_flows_back_and_the_task_finishes(tmp_path):
    home, _ = make_home(tmp_path)
    clarifier = FakeClarifier(["Trabajo"])

    engine, result = await run(home, [ASK], clarifier=clarifier)

    assert engine.replies[0].text == "Trabajo" and not engine.replies[0].is_error
    assert result.errores == []


async def test_request_carries_task_agent_question_and_options(tmp_path):
    home, _ = make_home(tmp_path)
    clarifier = FakeClarifier(["Trabajo"])

    await run(home, [ASK], clarifier=clarifier)

    [request] = clarifier.requests
    assert (request.task_id, request.agent, request.question, request.options) == (
        TASK_ID,
        "viernes",
        "¿Qué cuenta?",
        ["Personal", "Trabajo"],
    )
    assert len(request.request_id) == 32


async def test_request_ids_are_unique_per_question(tmp_path):
    home, _ = make_home(tmp_path)
    clarifier = FakeClarifier(["a", "b"])

    await run(home, [ASK, ASK], clarifier=clarifier)

    first, second = clarifier.requests
    assert first.request_id != second.request_id


async def test_question_and_options_are_masked_before_asking(tmp_path):
    home, _ = make_home(tmp_path)
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / ".env").write_text("TOKEN=s3cr3t-value\n")
    clarifier = FakeClarifier(["x"])
    ask = CallTool("tony.ask_user", {"question": "¿s3cr3t-value?", "options": ["s3cr3t-value"]})

    await run(home, [ask], clarifier=clarifier)

    [request] = clarifier.requests
    assert request.question == "¿***?" and request.options == ["***"]


async def test_timeout_is_an_error_reply_and_the_task_goes_on(tmp_path):
    home, _ = make_home(tmp_path, confirm=0.05)
    clarifier = FakeClarifier([HANG])

    engine, result = await run(home, [ASK, READ], clarifier=clarifier)

    first, second = engine.replies
    assert (first.text, first.is_error) == ("no answer from the user", True)
    assert second.text == "# Nota A\nComprar pan."
    assert result.errores == []
    assert clarifier.cancelled


async def test_timeout_does_not_trigger_denied_or_unconfirmed(tmp_path):
    home, _ = make_home(tmp_path, confirm=0.02)

    _, result = await run(home, [ASK, ASK, ASK, ASK], clarifier=FakeClarifier([HANG] * 4))

    assert result.errores == []


async def test_default_clarifier_has_no_channel_and_answers_at_once(tmp_path):
    home, _ = make_home(tmp_path)

    engine, result = await run(home, [ASK])

    assert (engine.replies[0].text, engine.replies[0].is_error) == (
        "no answer from the user",
        True,
    )
    assert result.errores == []
    assert isinstance(RunDeps(root=home, engine=engine).clarifier, NoChannelClarifier)


@pytest.mark.parametrize("answer", ["", "   ", None])
async def test_blank_answer_is_no_answer(tmp_path, answer):
    home, _ = make_home(tmp_path)

    engine, _ = await run(home, [ASK], clarifier=FakeClarifier([answer]))

    assert (engine.replies[0].text, engine.replies[0].is_error) == (
        "no answer from the user",
        True,
    )


async def test_clarifier_failure_is_no_answer(tmp_path):
    home, _ = make_home(tmp_path)

    engine, result = await run(home, [ASK], clarifier=FakeClarifier(error=RuntimeError("boom")))

    assert engine.replies[0].text == "no answer from the user"
    assert result.errores == []


async def test_answer_does_not_approve_a_later_confirm_call(tmp_path):
    home, notes = make_home(tmp_path)
    confirmer = FakeConfirmer([False])

    engine, result = await run(
        home, [ASK, DELETE], clarifier=FakeClarifier(["sí, borra todo"]), confirmer=confirmer
    )

    assert len(confirmer.requests) == 1 and confirmer.requests[0].tool == "filesystem.delete_file"
    assert engine.replies[0].text == "sí, borra todo"
    assert (notes / "a.md").exists()
    assert result.errores and "no autorizó" in result.errores[0]


async def test_slow_answer_beyond_tool_timeout_still_returns(tmp_path):
    home, _ = make_home(tmp_path, tool=0.02, confirm=5)

    engine, _ = await run(home, [ASK], clarifier=FakeClarifier(["tarde"], delay=0.15))

    assert (engine.replies[0].text, engine.replies[0].is_error) == ("tarde", False)


async def test_user_cancel_ends_the_wait(tmp_path):
    home, _ = make_home(tmp_path)
    clarifier = FakeClarifier([HANG])
    cancel = asyncio.Event()
    engine = FakeModelEngine([ASK, Final(structured=OK)])
    task = asyncio.create_task(
        run_task(
            "viernes", REQUEST, deps_for(home, engine, clarifier=clarifier, user_cancel=cancel)
        )
    )
    while not clarifier.requests:
        await asyncio.sleep(0.01)

    cancel.set()
    result = await task

    assert clarifier.cancelled
    assert result.errores == [USER_CANCELLED]


async def test_supervisor_cancellation_ends_the_wait(tmp_path):
    home, _ = make_home(tmp_path)
    deps = deps_for(home, FakeModelEngine([]), clarifier=FakeClarifier([HANG]))
    config = load_config(home)
    agent = load_agent(home, "viernes", config, native_tools=deps.native.keys())
    run_state = _prepare_run(agent, config, deps)

    asking = asyncio.create_task(_ask_user(run_state, deps, "¿Cuál?", []))
    await asyncio.sleep(0.01)
    run_state.supervisor.cancel("parada")

    assert await asyncio.wait_for(asking, 1) is None


async def test_clarifier_that_cancels_itself_is_no_answer(tmp_path):
    home, _ = make_home(tmp_path)
    deps = deps_for(
        home, FakeModelEngine([]), clarifier=FakeClarifier(error=asyncio.CancelledError())
    )
    config = load_config(home)
    agent = load_agent(home, "viernes", config, native_tools=deps.native.keys())

    answer = await _ask_user(_prepare_run(agent, config, deps), deps, "¿Cuál?", [])

    assert answer is None
