"""Tests for ClaudeSdkRunner result mapping, timeouts and errors."""

from __future__ import annotations

import time
from pathlib import Path

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
from tony.core.logging import JsonlEventSink
from tony.core.mcp import ToolCallOutcome
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.cancel import CancelToken
from tony.core.runner.claude_sdk import (
    ClaudeSdkRunner,
    assistant_text,
    build_options,
    qualified_from_sdk_name,
    result_from_message,
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


def make_runner(
    client: FakeClient,
    task_timeout_s: float = 5,
    gate=None,
    cleanup_budget_s: float = 5,
    cancel_token: CancelToken | None = None,
):
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
        cleanup_budget_s=cleanup_budget_s,
        cancel_token=cancel_token,
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


def text_delta(text: str) -> StreamEvent:
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


async def test_streamed_text_is_logged_once_as_the_whole_message() -> None:
    messages = [
        text_delta("abcd1234"),
        text_delta("SECRET"),
        AssistantMessage(content=[TextBlock(text="abcd1234SECRET")], model="m"),
        result_message(),
    ]

    _, sink, _ = await run(FakeClient(messages))

    assert sink.payloads("assistant.text") == [{"text": "abcd1234SECRET"}]


async def test_secret_split_across_stream_deltas_is_redacted_in_the_log(tmp_path: Path) -> None:
    sink = JsonlEventSink(tmp_path / "logs", "t1", secrets=["abcd1234SECRET"])
    messages = [
        text_delta("abcd1234"),
        text_delta("SECRET"),
        AssistantMessage(content=[TextBlock(text="abcd1234SECRET")], model="m"),
        result_message(),
    ]
    runner, _ = make_runner(FakeClient(messages))

    await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)
    sink.close()

    raw = sink.path.read_text(encoding="utf-8")
    assert "abcd1234" not in raw
    assert "SECRET" not in raw
    assert '"text": "***"' in raw


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


def test_assistant_text_joins_blocks_and_ignores_empty() -> None:
    message = AssistantMessage(content=[TextBlock(text="a"), TextBlock(text="b")], model="m")

    assert assistant_text(message) == "ab"
    assert assistant_text(AssistantMessage(content=[], model="m")) is None


def test_sdk_error_result_becomes_error_status_with_diagnostic() -> None:
    message = result_message(
        is_error=True, subtype="error_max_turns", result="Reached max turns", structured_output=None
    )

    result = result_from_message(message, fallback_text="x", steps=["fake.echo(a)"])

    assert result == TaskResult(
        status="error",
        resumen="Error del motor de ejecución: error_max_turns: Reached max turns",
        pasos=["fake.echo(a)"],
        errores=["error_max_turns: Reached max turns"],
    )


def test_sdk_error_without_text_reports_the_subtype_only() -> None:
    message = result_message(is_error=True, subtype="error_during_execution", result=None)

    result = result_from_message(message, fallback_text="x")

    assert result.status == "error"
    assert result.errores == ["error_during_execution"]


def test_sdk_error_prevails_over_valid_structured_output() -> None:
    message = result_message(is_error=True, subtype="error", structured_output=OK_OUTPUT)

    assert result_from_message(message, fallback_text="x").status == "error"


async def test_sdk_error_run_finishes_with_error_status_and_keeps_steps() -> None:
    client = FakeClient([result_message(is_error=True, subtype="error_max_turns", result="max")])
    runner, _ = make_runner(client)
    sink = ListEventSink()

    async def call_echo():
        await runner.proxy_handler("fake.echo")({"text": "hola"})

    client.before_messages = [call_echo]

    result = await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)

    assert result.status == "error"
    assert result.pasos == ["fake.echo(hola)"]
    assert sink.payloads("task.finished")[0]["status"] == "error"


async def test_partial_without_any_text_has_an_empty_summary() -> None:
    result, _, _ = await run(FakeClient([result_message(result=None, structured_output=None)]))

    assert result == TaskResult(status="partial", resumen="", errores=["respuesta no estructurada"])


async def test_slow_client_connect_counts_towards_the_task_timeout() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)], connect_delay=0.3)
    started = time.monotonic()

    result, _, _ = await run(client, task_timeout_s=0.05)

    assert result.status == "timeout"
    assert client.interrupts == 0
    assert time.monotonic() - started < 1


async def test_hanging_client_exit_is_cut_by_the_cleanup_budget() -> None:
    client = FakeClient(hang=True, exit_delay=10)
    started = time.monotonic()

    result, _, _ = await run(client, task_timeout_s=0.05, cleanup_budget_s=0.1)

    assert result.status == "timeout"
    assert client.interrupts == 1
    assert time.monotonic() - started < 1


async def test_model_result_survives_a_client_exit_that_exceeds_the_budget() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)], exit_delay=10)

    result, _, _ = await run(client, task_timeout_s=0.05, cleanup_budget_s=0.1)

    assert result == TaskResult(**OK_OUTPUT)


async def test_timeout_during_connection_does_not_wait_for_the_connect() -> None:
    client = FakeClient([result_message(structured_output=OK_OUTPUT)], connect_delay=2)
    started = time.monotonic()

    result, sink, _ = await run(client, task_timeout_s=0.2)

    assert result.status == "timeout"
    assert time.monotonic() - started < 1
    assert sink.payloads("task.finished")[0]["status"] == "timeout"


async def test_external_cancellation_interrupts_and_returns_cancelled() -> None:
    client = FakeClient(hang=True)
    token = CancelToken()
    runner, _ = make_runner(client, cancel_token=token)
    sink = ListEventSink()

    async def cancel_from_outside():
        token.cancel("user")

    client.before_messages = [cancel_from_outside]
    started = time.monotonic()

    result = await runner.run(worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), sink)

    assert result.status == "cancelled"
    assert result.errores == ["cancelada por el usuario"]
    assert result.resumen == "Tarea cancelada por el usuario."
    assert client.interrupts == 1
    assert sink.payloads("task.finished")[0]["status"] == "cancelled"
    assert time.monotonic() - started < 1


async def test_external_cancellation_with_another_reason_names_it() -> None:
    client = FakeClient(hang=True)
    token = CancelToken()
    runner, _ = make_runner(client, cancel_token=token)

    async def cancel_from_outside():
        token.cancel("shutdown")

    client.before_messages = [cancel_from_outside]

    result = await runner.run(
        worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), ListEventSink()
    )

    assert result.status == "cancelled"
    assert result.errores == ["cancelada: shutdown"]


def test_build_options_is_pure_and_keeps_worker_defences() -> None:
    settings = load_settings(None)
    options = build_options(
        worker_spec(), TaskRequest(objetivo="o"), fake_catalog(), settings, {}, lambda *a: None
    )

    assert options.tools == []
    assert options.permission_mode == "default"
    assert options.setting_sources == []
    assert "Bash" in options.disallowed_tools
