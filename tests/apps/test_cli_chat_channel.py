"""CliChannel rendering and confirmation prompt (specs/cli-chat)."""

from __future__ import annotations

import asyncio
import io
from typing import Any

from tests.fakes.stdin import FakeStdin
from tony.apps.cli.chat_channel import CliChannel
from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.core.channels.ports import (
    AssistantDelta,
    AssistantReply,
    AssistantWait,
    NeedsConfirmation,
    Notice,
    TaskEvent,
    TaskProgress,
    UserAccepted,
)
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.errors import OrchestratorError

REQUEST = NeedsConfirmation("t1", "c1", "filesystem.move_file", {"source": "a", "destination": "b"})


class RecordingConfirm:
    def __init__(self, error: str | None = None) -> None:
        self.calls: list[tuple[str, bool, str, dict[str, Any]]] = []
        self.error = error

    async def __call__(self, confirmation_id, approved, tool, args) -> None:
        self.calls.append((confirmation_id, approved, tool, args))
        if self.error:
            raise OrchestratorError(self.error)


def channel(lines: list, confirm=None, timeout_s: float = 1):
    err, out = io.StringIO(), io.StringIO()
    confirm = confirm or RecordingConfirm()
    return CliChannel("Viernes", FakeStdin(lines), confirm, timeout_s, err, out), confirm, err, out


async def test_affirmative_answer_sends_an_approval_bound_to_tool_and_args() -> None:
    cli, confirm, err, _ = channel(["sí\n"])

    await cli.send(REQUEST)

    assert err.getvalue() == (
        'Viernes quiere ejecutar filesystem.move_file {"destination": "b", "source": "a"}. '
        "¿Confirmas? [s/N] "
    )
    assert confirm.calls == [("c1", True, "filesystem.move_file", REQUEST.args)]


async def test_empty_answer_rejects() -> None:
    cli, confirm, _, _ = channel(["\n"])

    await cli.send(REQUEST)

    assert confirm.calls == [("c1", False, "filesystem.move_file", REQUEST.args)]


async def test_eof_rejects() -> None:
    cli, confirm, _, _ = channel([None])

    await cli.send(REQUEST)

    assert confirm.calls[0][1] is False


async def test_no_answer_reports_cancellation_without_confirming() -> None:
    cli, confirm, err, _ = channel([], timeout_s=0.05)

    await cli.send(REQUEST)

    assert "Sin respuesta en 0.05 s" in err.getvalue()
    assert "falta de confirmación" in err.getvalue()
    assert confirm.calls == []


async def test_stale_confirmation_is_reported_as_a_notice() -> None:
    cli, _, err, _ = channel(["s\n"], confirm=RecordingConfirm(error="invalid_confirmation"))

    await cli.send(REQUEST)

    assert "ya no es válida" in err.getvalue()


async def test_replies_go_to_stdout_and_the_rest_to_stderr() -> None:
    cli, _, err, out = channel([])

    await cli.send(AssistantReply("Hola", "Hola", "text"))
    await cli.send(AssistantReply("# Informe", "Informe listo", "voice"))
    await cli.send(AssistantReply("Sin resumen", None, "both"))
    await cli.send(AssistantWait("Dame un momento."))
    await cli.send(TaskProgress("t1", "filesystem.read_file", 1))
    await cli.send(Notice("Aviso"))

    assert out.getvalue() == "Hola\n🔊 Informe listo\n# Informe\nSin resumen\n"
    assert err.getvalue() == "Dame un momento.\n· filesystem.read_file\nAviso\n"


async def test_front_gate_and_worker_channel_never_show_two_prompts_at_once() -> None:
    err = io.StringIO()
    stdin = FakeStdin([])
    lock = asyncio.Lock()
    gate = CliConfirmGate("Jarvis", 1, stdin, err, lock=lock)
    confirm = RecordingConfirm()
    cli = CliChannel("Viernes", stdin, confirm, 1, err, io.StringIO(), lock=lock)
    front_request = ConfirmRequest.create("front", "fake.destroy", {})

    front = asyncio.ensure_future(gate.confirm(front_request))
    await asyncio.sleep(0)
    worker = asyncio.ensure_future(cli.send(REQUEST))
    for _ in range(5):
        await asyncio.sleep(0)
    assert err.getvalue().count("¿Confirmas? [s/N]") == 1
    assert "Jarvis quiere ejecutar fake.destroy" in err.getvalue()

    stdin.feed("s\n")
    assert await asyncio.wait_for(front, 1) is True
    for _ in range(5):
        await asyncio.sleep(0)
    assert err.getvalue().count("¿Confirmas? [s/N]") == 2
    stdin.feed("\n")
    await asyncio.wait_for(worker, 1)

    assert confirm.calls == [("c1", False, "filesystem.move_file", REQUEST.args)]


async def test_web_only_messages_are_ignored_by_the_terminal() -> None:
    cli, confirm, err, out = channel([])

    await cli.send(UserAccepted("m1", "text"))
    await cli.send(AssistantDelta("m2", "Hola"))
    await cli.send(
        TaskEvent("t1", None, "task.queued", {"objetivo": "x"}, 1, "2026-01-01T00:00:00Z")
    )

    assert out.getvalue() == "" and err.getvalue() == ""
    assert confirm.calls == []
