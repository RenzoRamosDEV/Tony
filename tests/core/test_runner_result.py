"""Tests for ClaudeSdkRunner result mapping, timeouts and errors."""

from __future__ import annotations

import pytest
from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock

from tests.core.runner_helpers import (
    FailingClient,
    FakeClient,
    fake_catalog,
    result_message,
    worker_spec,
)
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.mcp import ToolCallOutcome
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.claude_sdk import (
    ClaudeSdkRunner,
    assistant_text,
    qualified_from_sdk_name,
    result_from_message,
    stream_text,
    usage_from_message,
)

OK_OUTPUT = {
    "status": "ok",
    "resumen": "Listo",
    "datos": ["a.md"],
    "pasos": ["listar"],
    "errores": [],
}


async def echo_call(qualified, args, timeout):
    return ToolCallOutcome(ok=True, content="hola", duration_ms=1)


def make_runner(client: FakeClient, task_timeout_s: float = 5, gate=None):
    settings = load_settings(None)
    settings.limits.task_timeout_s = task_timeout_s
    captured = {}

    def factory(options):
        captured["options"] = options
        return client

    runner = ClaudeSdkRunner(
        settings=settings,
        task_id="t1",
        gate=gate or AutoConfirmGate(True),
        call=echo_call,
        client_factory=factory,
    )
    return runner, captured


async def run(client: FakeClient, **kwargs):
    runner, captured = make_runner(client, **kwargs)
    sink = ListEventSink()
    result = await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)
    return result, sink, captured


async def test_valid_structured_output_is_returned_verbatim() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)])

    result, sink, captured = await run(client)

    assert result == TaskResult(**OK_OUTPUT)
    assert sink.types()[0] == "task.started"
    assert sink.types()[-1] == "task.finished"
    assert sink.payloads("task.finished")[0] == {
        "status": "ok",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_cost_usd": 0.0123,
            "num_turns": 3,
        },
    }
    assert client.prompts[0].startswith("Resuelve la siguiente tarea")
    assert captured["options"].model == "claude-sonnet-5-5"


async def test_missing_structured_output_becomes_partial() -> None:
    client = FakeClient([result_message(structured_output=None, result="He listado los ficheros.")])

    result, _, _ = await run(client)

    assert result == TaskResult(
        status="partial",
        resumen="He listado los ficheros.",
        datos=None,
        pasos=[],
        errores=["respuesta no estructurada"],
    )


async def test_invalid_structured_output_becomes_partial() -> None:
    client = FakeClient([result_message(structured_output={"status": "done"}, result="texto")])

    result, _, _ = await run(client)

    assert result.status == "partial"
    assert result.resumen == "texto"
    assert result.errores == ["respuesta no estructurada"]


async def test_partial_falls_back_to_last_assistant_text_when_result_empty() -> None:
    messages = [
        AssistantMessage(content=[TextBlock(text="Último texto")], model="m"),
        result_message(result=None, structured_output=None),
    ]

    result, sink, _ = await run(FakeClient(messages))

    assert result.resumen == "Último texto"
    assert ("assistant.text", {"text": "Último texto"}) in sink.events


async def test_stream_text_deltas_become_assistant_text_events() -> None:
    delta = StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hol"}},
    )
    messages = [
        delta,
        AssistantMessage(content=[TextBlock(text="Hola")], model="m"),
        result_message(),
    ]

    _, sink, _ = await run(FakeClient(messages))

    assert sink.payloads("assistant.text") == [{"text": "Hol"}]


async def test_cancelled_state_prevails_over_model_output() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)])
    runner, captured = make_runner(client, gate=AutoConfirmGate(False))
    sink = ListEventSink()

    async def reject_destroy():
        await runner.proxy_handler("fake.destroy")({})

    client.before_messages = [reject_destroy]

    result = await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)

    assert result.status == "cancelled"
    assert result.resumen == "Tarea cancelada: el usuario no confirmó fake.destroy."
    assert result.errores == ["Tool fake.destroy no confirmada por el usuario"]
    assert client.interrupts == 1
    assert sink.payloads("task.finished")[0]["status"] == "cancelled"


async def test_engine_exception_becomes_error_without_trace() -> None:
    result, sink, _ = await run(FailingClient(ConnectionError("connection refused")))

    assert result.status == "error"
    assert result.errores == ["connection refused"]
    assert "Traceback" not in result.resumen
    assert sink.payloads("task.finished")[0]["status"] == "error"


async def test_task_timeout_interrupts_and_returns_timeout() -> None:
    client = FakeClient(hang=True)

    result, sink, _ = await run(client, task_timeout_s=0.2)

    assert result.status == "timeout"
    assert client.interrupts == 1
    assert sink.payloads("task.finished")[0]["status"] == "timeout"


def test_result_from_message_and_usage_are_pure() -> None:
    message = result_message(structured_output=OK_OUTPUT, usage={"input_tokens": 1}, num_turns=1)

    assert result_from_message(message, fallback_text="x") == TaskResult(**OK_OUTPUT)
    assert usage_from_message(message) == {
        "input_tokens": 1,
        "output_tokens": 0,
        "total_cost_usd": 0.0123,
        "num_turns": 1,
    }


def test_usage_of_missing_result_is_zero() -> None:
    assert usage_from_message(None) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_cost_usd": 0.0,
        "num_turns": 0,
    }


async def test_task_started_payload_and_proxy_wiring() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)])

    _, sink, captured = await run(client)

    assert sink.payloads("task.started") == [{"agent": "viernes", "objetivo": "o"}]
    assert list(captured["options"].mcp_servers) == ["fake"]
    assert captured["options"].allowed_tools == ["mcp__fake__*"]


async def test_timeout_and_cancelled_results_keep_executed_steps() -> None:
    client = FakeClient(hang=True)
    runner, _ = make_runner(client, task_timeout_s=0.2)
    sink = ListEventSink()

    async def call_echo():
        await runner.proxy_handler("fake.echo")({"text": "hola"})

    client.before_messages = [call_echo]

    result = await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)

    assert result.status == "timeout"
    assert result.pasos == ["fake.echo(hola)"]
    assert result.errores == ["timeout de tarea tras 0.2 s"]


def test_result_from_message_without_message_is_partial_with_fallback() -> None:
    assert result_from_message(None, fallback_text="último") == TaskResult(
        status="partial", resumen="último", errores=["respuesta no estructurada"]
    )


def test_result_prefers_result_text_over_fallback() -> None:
    assert result_from_message(result_message(result="final"), fallback_text="x").resumen == "final"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mcp__fs__read_file", "fs.read_file"),
        ("mcp__fs__read__file", "fs.read__file"),
        ("mcp__fs", None),
        ("mcp____x", None),
        ("mcp__fs__", None),
        ("Bash", None),
    ],
)
def test_qualified_from_sdk_name(name: str, expected: str | None) -> None:
    assert qualified_from_sdk_name(name) == expected


@pytest.mark.parametrize(
    "event",
    [
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}},
        {"type": "message_start"},
        {},
    ],
)
def test_stream_text_ignores_non_text_events(event: dict) -> None:
    assert stream_text(StreamEvent(uuid="u", session_id="s", event=event)) is None


def test_assistant_text_joins_blocks_and_ignores_empty() -> None:
    message = AssistantMessage(content=[TextBlock(text="a"), TextBlock(text="b")], model="m")

    assert assistant_text(message) == "ab"
    assert assistant_text(AssistantMessage(content=[], model="m")) is None
