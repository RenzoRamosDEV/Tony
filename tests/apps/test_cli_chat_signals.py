"""Ctrl+C handling of the chat REPL (specs/cli-chat: cancelación con Ctrl+C)."""

from __future__ import annotations

import asyncio
import io
import os
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from tests.core.channels.test_chat_session import Harness, delegating
from tests.fakes.stdin import FakeStdin
from tony.apps.cli.repl import ChatRepl
from tony.apps.cli.stdin_dispatcher import StdinDispatcher
from tony.core.orchestrator.task import TaskStatus
from tony.core.runner import TaskResult


def send_sigint() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def make_repl(h: Harness, stdin: FakeStdin, out: io.StringIO, close_timeout_s: float = 0.2):
    return ChatRepl(
        h.session,
        StdinDispatcher(stdin, out),
        h.memory,
        h.settings,
        out=out,
        stdout=io.StringIO(),
        close_timeout_s=close_timeout_s,
    )


async def test_first_ctrl_c_cancels_the_task_and_shows_the_prompt_again(tmp_path: Path) -> None:
    h = Harness(tmp_path, [delegating("larga")])
    h.factory.scripts["larga"] = [("sleep", 100)]
    await h.start()
    stdin = FakeStdin(["tarea larga\n"])
    out = io.StringIO()
    repl = make_repl(h, stdin, out)
    running = asyncio.ensure_future(repl.run())
    await h.clock.settle()
    task = next(iter(h.orchestrator.tasks.values()))
    assert task.status == TaskStatus.RUNNING

    send_sigint()
    await h.clock.settle()

    assert task.status == TaskStatus.CANCELLED
    assert out.getvalue().count("tú> ") == 2
    stdin.feed("/salir\n")
    assert await asyncio.wait_for(running, 1) == 0


class StuckRunner:
    """Ignores cancellation: the task never finishes."""

    async def run(self, spec, request, tools, events) -> TaskResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_second_ctrl_c_exits_quickly_even_with_stdin_blocked(tmp_path: Path) -> None:
    h = Harness(tmp_path, [delegating("atascada")])
    h.factory.custom_runners["atascada"] = StuckRunner()
    await h.start()
    stdin = FakeStdin(["tarea atascada\n"])
    out = io.StringIO()
    repl = make_repl(h, stdin, out)
    running = asyncio.ensure_future(repl.run())
    await h.clock.settle()
    send_sigint()
    await h.clock.settle()
    task = next(iter(h.orchestrator.tasks.values()))
    assert task.status == TaskStatus.CANCELLED
    assert not task.finished.is_set()

    started = time.monotonic()
    send_sigint()
    code = await asyncio.wait_for(running, 2)

    assert code == 0
    assert time.monotonic() - started < 2
    assert h.runner.closed is True


async def test_ctrl_c_without_a_task_exits_the_repl(tmp_path: Path) -> None:
    h = Harness(tmp_path, [])
    await h.start()
    out = io.StringIO()
    repl = make_repl(h, FakeStdin([]), out)
    running = asyncio.ensure_future(repl.run())
    await h.clock.settle()

    send_sigint()

    assert await asyncio.wait_for(running, 1) == 0


async def failing_turn(prompt: str, handlers: Any) -> dict[str, Any]:
    raise ConnectionError("cli died")


async def test_turn_error_still_closes_the_session(tmp_path: Path) -> None:
    h = Harness(tmp_path, [failing_turn])
    await h.start()
    repl = make_repl(h, FakeStdin(["hola\n"]), io.StringIO())

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(repl.run(), 1)

    assert h.runner.closed is True
    assert h.factory.closed is True


async def test_cancel_command_typed_during_a_task_cancels_it(tmp_path: Path) -> None:
    h = Harness(tmp_path, [delegating("larga")])
    h.factory.scripts["larga"] = [("sleep", 100)]
    await h.start()
    stdin = FakeStdin(["tarea larga\n"])
    out = io.StringIO()
    repl = make_repl(h, stdin, out)
    running = asyncio.ensure_future(repl.run())
    await h.clock.settle()
    task = next(iter(h.orchestrator.tasks.values()))
    assert task.status == TaskStatus.RUNNING

    stdin.feed("hola\n")
    await h.clock.settle()
    assert "Espera a que termine la tarea." in out.getvalue()
    assert task.status == TaskStatus.RUNNING

    stdin.feed("/cancel\n")
    await h.clock.settle()

    assert task.status == TaskStatus.CANCELLED
    assert "Tarea cancelada." in out.getvalue()
    stdin.feed("/salir\n")
    assert await asyncio.wait_for(running, 1) == 0


async def test_before_close_hook_runs_before_the_session_closes(tmp_path: Path) -> None:
    h = Harness(tmp_path, [])
    await h.start()
    order: list[str] = []
    original_close = h.session.close

    async def before_close() -> None:
        order.append("hook")

    async def closing() -> None:
        order.append("session")
        await original_close()

    h.session.close = closing  # type: ignore[method-assign]
    repl = ChatRepl(
        h.session,
        StdinDispatcher(FakeStdin(["/salir\n"]), io.StringIO()),
        h.memory,
        h.settings,
        out=io.StringIO(),
        stdout=io.StringIO(),
        before_close=before_close,
    )

    assert await asyncio.wait_for(repl.run(), 1) == 0
    assert order == ["hook", "session"]
