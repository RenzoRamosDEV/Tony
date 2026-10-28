"""Ctrl+C handling of the chat REPL (specs/cli-chat: cancelación con Ctrl+C)."""

from __future__ import annotations

import asyncio
import io
import os
import signal
import time
from pathlib import Path

from tests.core.channels.test_chat_session import Harness, delegating
from tests.fakes.stdin import FakeStdin
from tony.apps.cli.repl import ChatRepl
from tony.core.orchestrator.task import TaskStatus
from tony.core.runner import TaskResult


def send_sigint() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def make_repl(h: Harness, stdin: FakeStdin, out: io.StringIO, close_timeout_s: float = 0.2):
    return ChatRepl(
        h.session,
        stdin,
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
