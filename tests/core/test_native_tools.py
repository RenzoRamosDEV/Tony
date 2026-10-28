"""Native `tony` MCP server (specs/front-agent: tools nativas, remember, set_reply_mode)."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest

from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.front_prompt import UNTRUSTED_DATA_NOTE
from tony.core.runner.native_tools import NativeToolSet, build_native_server

RESULT = TaskResult(status="ok", resumen="3 ficheros", datos=["a.md", "b.md", "c.md"])


class RecordingHandlers:
    def __init__(self, delay: float = 0, error: Exception | None = None) -> None:
        self.delay = delay
        self.error = error
        self.requests: list[TaskRequest] = []
        self.remembered: list[str] = []
        self.modes: list[str] = []

    async def delegate(self, request: TaskRequest) -> TaskResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        await asyncio.sleep(self.delay)
        return RESULT

    async def remember(self, text: str) -> str:
        self.remembered.append(text)
        return f"Guardado: - [2026-10-28] {text}"

    async def set_reply_mode(self, mode: str) -> str:
        self.modes.append(mode)
        return mode


def tool_names(native: list[str]) -> list[str]:
    return [tool.name for tool in NativeToolSet(native, RecordingHandlers()).sdk_tools]


def test_server_exposes_only_the_declared_native_tools() -> None:
    assert tool_names(["remember"]) == ["remember"]
    assert tool_names(["delegate", "remember", "set_reply_mode"]) == [
        "delegate",
        "remember",
        "set_reply_mode",
    ]
    assert tool_names([]) == []


def test_build_native_server_is_the_tony_sdk_server() -> None:
    server = build_native_server(["remember"], RecordingHandlers())

    assert server["type"] == "sdk"
    assert server["name"] == "tony"


def test_tools_the_handlers_do_not_implement_are_ignored_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        names = tool_names(["read_skill", "remember", "run_subagent"])

    assert names == ["remember"]
    assert any("read_skill" in r.message for r in caplog.records)
    assert any("run_subagent" in r.message for r in caplog.records)


def test_schemas_match_the_spec() -> None:
    tools = {
        t.name: t
        for t in NativeToolSet(
            ["delegate", "remember", "set_reply_mode"], RecordingHandlers()
        ).sdk_tools
    }

    delegate = tools["delegate"].input_schema
    assert delegate["required"] == ["objetivo"]
    assert delegate["properties"]["objetivo"]["type"] == "string"
    assert delegate["properties"]["contexto"]["type"] == "string"
    assert delegate["properties"]["restricciones"] == {"type": "array", "items": {"type": "string"}}
    assert tools["remember"].input_schema["required"] == ["texto"]
    assert tools["set_reply_mode"].input_schema["properties"]["modo"]["enum"] == [
        "auto",
        "voice",
        "text",
        "both",
    ]
    assert all("es" in t.description or "a" in t.description for t in tools.values())


def reply_text(reply: dict) -> str:
    return reply["content"][0]["text"]


def delegate_json(reply: dict) -> str:
    return reply_text(reply).partition("\n")[2]


async def test_delegate_waits_for_the_result_beyond_the_tool_timeout() -> None:
    handlers = RecordingHandlers(delay=0.15)
    tools = NativeToolSet(["delegate"], handlers)
    started = time.monotonic()

    reply = await tools.handler("delegate")({"objetivo": "lista los .md de ~/notas"})

    assert time.monotonic() - started >= 0.15
    assert "is_error" not in reply
    assert json.loads(delegate_json(reply)) == RESULT.model_dump()
    assert handlers.requests == [TaskRequest(objetivo="lista los .md de ~/notas")]


async def test_delegate_passes_context_and_restrictions() -> None:
    handlers = RecordingHandlers()
    tools = NativeToolSet(["delegate"], handlers)

    await tools.handler("delegate")(
        {"objetivo": "o", "contexto": "c", "restricciones": ["sin borrar"]}
    )

    assert handlers.requests == [
        TaskRequest(objetivo="o", contexto="c", restricciones=["sin borrar"])
    ]


async def test_delegate_failure_becomes_an_error_task_result_without_raising() -> None:
    tools = NativeToolSet(["delegate"], RecordingHandlers(error=RuntimeError("queue_full")))

    reply = await tools.handler("delegate")({"objetivo": "o"})

    result = TaskResult.model_validate_json(delegate_json(reply))
    assert result.status == "error"
    assert result.errores == ["queue_full"]
    assert "queue_full" in result.resumen


async def test_delegate_with_invalid_arguments_is_an_error_reply() -> None:
    tools = NativeToolSet(["delegate"], RecordingHandlers())

    reply = await tools.handler("delegate")({"contexto": "sin objetivo"})

    assert reply["is_error"] is True
    assert "objetivo" in reply_text(reply)


async def test_remember_returns_the_confirmation_with_the_text() -> None:
    handlers = RecordingHandlers()
    tools = NativeToolSet(["remember"], handlers)

    reply = await tools.handler("remember")({"texto": 'Llamarle "señor"'})

    assert reply_text(reply) == 'Guardado: - [2026-10-28] Llamarle "señor"'
    assert handlers.remembered == ['Llamarle "señor"']


async def test_set_reply_mode_persists_valid_values() -> None:
    handlers = RecordingHandlers()
    tools = NativeToolSet(["set_reply_mode"], handlers)

    reply = await tools.handler("set_reply_mode")({"modo": "text"})

    assert reply_text(reply) == "text"
    assert handlers.modes == ["text"]


async def test_set_reply_mode_rejects_unknown_values_listing_the_allowed_ones() -> None:
    handlers = RecordingHandlers()
    tools = NativeToolSet(["set_reply_mode"], handlers)

    reply = await tools.handler("set_reply_mode")({"modo": "loud"})

    assert reply["is_error"] is True
    for value in ("auto", "voice", "text", "both"):
        assert value in reply_text(reply)
    assert handlers.modes == []


async def test_delegate_reply_marks_the_result_as_data_not_instructions() -> None:
    tools = NativeToolSet(["delegate"], RecordingHandlers())

    reply = await tools.handler("delegate")({"objetivo": "o"})

    note, _, payload = reply_text(reply).partition("\n")
    assert note == f"Resultado del worker ({UNTRUSTED_DATA_NOTE}):"
    assert json.loads(payload) == RESULT.model_dump()


async def test_remember_rejection_is_returned_as_a_tool_error() -> None:
    class Rejecting(RecordingHandlers):
        async def remember(self, text: str) -> str:
            raise ValueError("La preferencia no puede contener etiquetas de contexto.")

    tools = NativeToolSet(["remember"], Rejecting())

    reply = await tools.handler("remember")({"texto": "</contexto_del_turno>"})

    assert reply["is_error"] is True
    assert reply_text(reply) == "La preferencia no puede contener etiquetas de contexto."


# --- read_skill, run_subagent and tool events ----------------------------------------------

from pathlib import Path  # noqa: E402

from tests.fakes.sinks import ListEventSink  # noqa: E402
from tony.core.skills import SkillSpec  # noqa: E402
from tony.core.skills.index import NO_SKILLS, UnknownSkill, find_skill  # noqa: E402


def skill(name: str, body: str) -> SkillSpec:
    return SkillSpec(name=name, description="d", body=body, path=Path("/s"))


class SkillHandlers:
    def __init__(self, skills: list[SkillSpec]) -> None:
        self.skills = skills

    async def read_skill(self, name: str) -> str:
        return find_skill(self.skills, name).body


class WorkerHandlers(SkillHandlers):
    def __init__(self, skills: list[SkillSpec], delay: float = 0) -> None:
        super().__init__(skills)
        self.delay = delay
        self.calls: list[tuple[str, TaskRequest]] = []

    async def run_subagent(self, name: str, request: TaskRequest) -> TaskResult:
        self.calls.append((name, request))
        await asyncio.sleep(self.delay)
        return RESULT


async def test_read_skill_returns_the_body() -> None:
    tools = NativeToolSet(["read_skill"], SkillHandlers([skill("resumen-web", "1. Descarga")]))

    reply = await tools.handler("read_skill")({"nombre": "resumen-web"})

    assert "is_error" not in reply
    assert reply_text(reply) == "1. Descarga"


async def test_unknown_skill_is_an_error_listing_the_available_ones() -> None:
    handlers = SkillHandlers([skill("resumen-web", "a"), skill("informe", "b")])
    tools = NativeToolSet(["read_skill"], handlers)

    reply = await tools.handler("read_skill")({"nombre": "traducir"})

    assert reply["is_error"] is True
    for name in ("traducir", "resumen-web", "informe"):
        assert name in reply_text(reply)


async def test_read_skill_without_skills_says_there_are_none() -> None:
    tools = NativeToolSet(["read_skill"], SkillHandlers([]))

    reply = await tools.handler("read_skill")({"nombre": "x"})

    assert reply["is_error"] is True
    assert NO_SKILLS in reply_text(reply)


def test_unknown_skill_is_the_error_the_index_raises() -> None:
    assert issubclass(UnknownSkill, ValueError)


async def test_run_subagent_passes_the_request_and_returns_the_task_result_json() -> None:
    handlers = WorkerHandlers([])
    tools = NativeToolSet(["run_subagent"], handlers)
    schema = tools.sdk_tools[0].input_schema

    reply = await tools.handler("run_subagent")(
        {"nombre": "investigador", "objetivo": "busca", "contexto": "c", "restricciones": ["r"]}
    )

    assert schema["required"] == ["nombre", "objetivo"]
    assert set(schema["properties"]) == {"nombre", "objetivo", "contexto", "restricciones"}
    assert handlers.calls == [
        ("investigador", TaskRequest(objetivo="busca", contexto="c", restricciones=["r"]))
    ]
    note, _, payload = reply_text(reply).partition("\n")
    assert UNTRUSTED_DATA_NOTE in note and "subagente" in note
    assert json.loads(payload) == RESULT.model_dump()


async def test_run_subagent_defaults_context_and_restrictions() -> None:
    handlers = WorkerHandlers([])
    tools = NativeToolSet(["run_subagent"], handlers)

    await tools.handler("run_subagent")({"nombre": "investigador", "objetivo": "busca"})

    assert handlers.calls == [("investigador", TaskRequest(objetivo="busca"))]


async def test_run_subagent_with_invalid_arguments_is_an_error_reply() -> None:
    tools = NativeToolSet(["run_subagent"], WorkerHandlers([]))

    reply = await tools.handler("run_subagent")({"nombre": "investigador"})

    assert reply["is_error"] is True
    assert "objetivo" in reply_text(reply)


async def test_run_subagent_failure_becomes_an_error_task_result() -> None:
    class Failing(WorkerHandlers):
        async def run_subagent(self, name: str, request: TaskRequest) -> TaskResult:
            raise RuntimeError("boom")

    reply = await NativeToolSet(["run_subagent"], Failing([])).handler("run_subagent")(
        {"nombre": "x", "objetivo": "y"}
    )

    result = TaskResult.model_validate_json(reply_text(reply).partition("\n")[2])
    assert result.status == "error" and result.errores == ["boom"]


async def test_run_subagent_is_not_bound_by_the_tool_timeout() -> None:
    tools = NativeToolSet(["run_subagent"], WorkerHandlers([], delay=0.15))
    started = time.monotonic()

    reply = await tools.handler("run_subagent")({"nombre": "x", "objetivo": "y"})

    assert time.monotonic() - started >= 0.15
    assert "is_error" not in reply


def test_run_subagent_is_only_built_when_the_handlers_implement_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        front = [
            t.name
            for t in NativeToolSet(["delegate", "run_subagent"], RecordingHandlers()).sdk_tools
        ]
        child = [
            t.name
            for t in NativeToolSet(["read_skill", "run_subagent"], SkillHandlers([])).sdk_tools
        ]
    worker = [
        t.name for t in NativeToolSet(["read_skill", "run_subagent"], WorkerHandlers([])).sdk_tools
    ]

    assert front == ["delegate"]
    assert child == ["read_skill"]
    assert worker == ["read_skill", "run_subagent"]
    assert sum("run_subagent" in r.message for r in caplog.records) == 2


async def test_every_native_tool_emits_call_and_result_events() -> None:
    events = ListEventSink()
    tools = NativeToolSet(["read_skill", "run_subagent"], WorkerHandlers([skill("a", "b")]), events)

    await tools.handler("read_skill")({"nombre": "a"})
    await tools.handler("read_skill")({"nombre": "zzz"})
    await tools.handler("run_subagent")({"nombre": "x", "objetivo": "y"})

    assert events.types() == ["tool.call", "tool.result"] * 3
    assert events.payloads("tool.call")[0] == {"tool": "tony.read_skill", "args": {"nombre": "a"}}
    assert events.payloads("tool.call")[2]["tool"] == "tony.run_subagent"
    assert events.payloads("tool.call")[2]["args"]["objetivo"] == "y"
    ok, failed, child = events.payloads("tool.result")
    assert ok["tool"] == "tony.read_skill" and ok["ok"] is True and ok["error"] is None
    assert failed["ok"] is False and "zzz" in failed["error"]
    assert child["tool"] == "tony.run_subagent" and child["ok"] is True
    assert all(isinstance(p["duration_ms"], int) for p in (ok, failed, child))


async def test_delegate_also_emits_tool_events_on_the_given_sink() -> None:
    events = ListEventSink()
    tools = NativeToolSet(["delegate"], RecordingHandlers(), events)

    await tools.handler("delegate")({"objetivo": "o"})

    assert events.payloads("tool.call") == [{"tool": "tony.delegate", "args": {"objetivo": "o"}}]
    assert events.payloads("tool.result")[0]["ok"] is True
