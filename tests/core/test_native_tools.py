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


def test_unsupported_native_tools_are_ignored_with_a_warning(
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
