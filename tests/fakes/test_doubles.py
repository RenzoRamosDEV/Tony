import asyncio

import pytest

from tests.fakes.confirm import HANG, FakeConfirmer, FakeWording
from tests.fakes.fake_engine import (
    ByAgentEngine,
    CallTool,
    FakeModelEngine,
    Final,
    Hang,
    Raise,
    ScriptError,
)
from tests.fakes.guards import RecordingGuard
from tests.fakes.sinks import ListEventSink
from tony.core.events.messages import Ruling, TaskRequest, ToolCall
from tony.core.guard.confirm import ConfirmationRequest
from tony.core.orchestrator.ports import EngineOutcome, ProxiedTool, ToolReply, Usage

REQUEST = TaskRequest(objetivo="o")


def request(question):
    return ConfirmationRequest(task_id="t", tool="x", args_preview="{}", question=question)


def tool(tool_id, log):
    async def handler(args):
        log.append((tool_id, args))
        return ToolReply(text=f"{tool_id}:{args}")

    return ProxiedTool(id=tool_id, description="d", input_schema={}, handler=handler)


async def run(engine, tools):
    return await engine.run(None, REQUEST, tools, "model-x")


async def test_executes_scripted_calls_in_order_and_records_replies():
    log = []
    engine = FakeModelEngine(
        [
            CallTool("fs.list", {"path": "."}),
            CallTool("fs.read", {"path": "a.md"}),
            Final(structured={"resumen": "r"}, usage=Usage(5, 2)),
        ]
    )

    outcome = await run(engine, [tool("fs.list", log), tool("fs.read", log)])

    assert log == [("fs.list", {"path": "."}), ("fs.read", {"path": "a.md"})]
    assert [reply.text for reply in engine.replies] == [
        "fs.list:{'path': '.'}",
        "fs.read:{'path': 'a.md'}",
    ]
    assert outcome == EngineOutcome(text="", structured={"resumen": "r"}, usage=[Usage(5, 2)])


async def test_records_what_it_was_given():
    engine = FakeModelEngine([Final(text="hola")])

    await run(engine, [tool("fs.list", [])])

    assert engine.offered == ["fs.list"]
    assert (engine.request, engine.model_id) == (REQUEST, "model-x")


async def test_structured_answer_may_be_built_from_replies():
    engine = FakeModelEngine(
        [
            CallTool("fs.read", {}),
            Final(structured=lambda replies: {"datos": replies[0].text}),
        ]
    )

    outcome = await run(engine, [tool("fs.read", [])])

    assert outcome.structured == {"datos": "fs.read:{}"}


async def test_fails_clearly_when_scripted_tool_not_offered():
    engine = FakeModelEngine([CallTool("fs.write", {}), Final(text="x")])

    with pytest.raises(ScriptError, match="fs.write"):
        await run(engine, [tool("fs.read", [])])


async def test_fails_clearly_without_final_step():
    engine = FakeModelEngine([])

    with pytest.raises(ScriptError, match="Final"):
        await run(engine, [])


async def test_hang_never_returns():
    engine = FakeModelEngine([Hang()])

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(run(engine, []), 0.05)


async def test_recording_guard_returns_ruling_and_records_envelope():
    denied = Ruling(verdict="deny", rule="x.y/deny")
    guard = RecordingGuard(denied)
    call = ToolCall(task_id="t", agent="a", tool="x.y", args={})

    assert await guard.decide(call) == denied
    assert guard.calls == [call]


async def test_recording_guard_allows_by_default():
    ruling = await RecordingGuard().decide(ToolCall(task_id="t", agent="a", tool="x", args={}))

    assert ruling.verdict == "allow"


def test_list_event_sink_keeps_events_in_order():
    sink = ListEventSink()

    sink.emit({"type": "a"})
    sink.emit({"type": "b", "v": 1})

    assert sink.events == [{"type": "a"}, {"type": "b", "v": 1}]
    assert sink.types() == ["a", "b"]


@pytest.mark.parametrize("answer", [True, False, None])
async def test_fake_confirmer_returns_scripted_answers_and_records_questions(answer):
    confirmer = FakeConfirmer([answer, True])

    assert await confirmer.ask(request("¿Q1?")) is answer
    assert await confirmer.ask(request("¿Q2?")) is True
    assert confirmer.questions == ["¿Q1?", "¿Q2?"]


async def test_fake_confirmer_can_hang():
    confirmer = FakeConfirmer([HANG])

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(confirmer.ask(request("¿Q?")), 0.05)
    assert confirmer.questions == ["¿Q?"]


async def test_fake_confirmer_without_script_answers_no():
    assert await FakeConfirmer().ask(request("¿Q?")) is False


async def test_fake_wording_returns_text_and_records_inputs():
    wording = FakeWording(text="Acción: x. Regla: r. ¿Autoriza?")

    text = await wording.word("fs.delete", '{"path": "a"}', "r")

    assert text == "Acción: x. Regla: r. ¿Autoriza?"
    assert wording.inputs == [("fs.delete", '{"path": "a"}', "r")]


async def test_fake_wording_can_raise():
    wording = FakeWording(error=RuntimeError("model down"))

    with pytest.raises(RuntimeError, match="model down"):
        await wording.word("t", "p", "r")
    assert wording.inputs == [("t", "p", "r")]


async def test_fake_wording_can_delay():
    wording = FakeWording(text="late", delay=1.0)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(wording.word("t", "p", "r"), 0.05)


class _Spec:
    def __init__(self, name):
        self.name = name


async def test_by_agent_engine_dispatches_by_spec_name():

    log = []
    engine = ByAgentEngine(
        {
            "viernes": [CallTool("fs.read", {}), Final(structured={"resumen": "v"})],
            "resumidor": [Final(structured={"resumen": "r"})],
        }
    )

    sub = await engine.run(_Spec("resumidor"), REQUEST, [], "m")
    main = await engine.run(_Spec("viernes"), REQUEST, [tool("fs.read", log)], "m")

    assert (sub.structured, main.structured) == ({"resumen": "r"}, {"resumen": "v"})
    assert engine.calls == ["resumidor", "viernes"]
    assert engine.engines["viernes"].replies[0].text == "fs.read:{}"


async def test_by_agent_engine_unknown_agent_fails():

    with pytest.raises(ScriptError):
        await ByAgentEngine({}).run(_Spec("nadie"), REQUEST, [], "m")


async def test_raise_step_raises_the_error():

    with pytest.raises(RuntimeError, match="model down"):
        await FakeModelEngine([Raise(RuntimeError("model down"))]).run(None, REQUEST, [], "m")
