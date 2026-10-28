"""Tests for the interactive CLI confirmation gate."""

from __future__ import annotations

import asyncio
import io
import os
import time

import pytest

from tony.apps.cli.confirm_gate import CliConfirmGate, StdinLines
from tony.core.mcp import ConfirmRequest

REQUEST = ConfirmRequest.create("t", "filesystem.write_file", {"path": "a.md"})
OTHER = ConfirmRequest.create("t", "filesystem.delete", {"path": "b.md"})
PROMPT = 'Viernes quiere ejecutar filesystem.write_file con {"path": "a.md"}. ¿Confirmas? [s/N] '


class FakeLines:
    """Scripted answers; None stands for EOF. Suspends once per read like a real source."""

    def __init__(self, answers: list[str | None], out: io.StringIO | None = None) -> None:
        self.answers = list(answers)
        self.out = out
        self.seen_output: list[str] = []

    async def readline(self) -> str | None:
        await asyncio.sleep(0)
        if self.out is not None:
            self.seen_output.append(self.out.getvalue())
        if not self.answers:
            await asyncio.Event().wait()
        return self.answers.pop(0)


def gate(answers: list[str | None], timeout_s: float = 5, out: io.StringIO | None = None):
    out = out if out is not None else io.StringIO()
    lines = FakeLines(answers, out)
    return CliConfirmGate("Viernes", timeout_s=timeout_s, lines=lines, out=out), lines, out


@pytest.mark.parametrize("answer", ["Sí\n", "si\n", "s\n", "S\n", " sí \n", "SI"])
async def test_affirmative_answers_approve(answer: str) -> None:
    confirm_gate, _, _ = gate([answer])

    assert await confirm_gate.confirm(REQUEST) is True


@pytest.mark.parametrize("answer", ["n\n", "\n", "no\n", "yes\n", "sí claro\n", "y\n", ""])
async def test_other_answers_reject(answer: str) -> None:
    confirm_gate, _, _ = gate([answer])

    assert await confirm_gate.confirm(REQUEST) is False


async def test_eof_rejects() -> None:
    confirm_gate, _, _ = gate([None])

    assert await confirm_gate.confirm(REQUEST) is False


async def test_timeout_rejects_and_says_so() -> None:
    confirm_gate, _, out = gate([], timeout_s=0.05)

    assert await confirm_gate.confirm(REQUEST) is False
    assert "se rechaza" in out.getvalue()


async def test_prompt_goes_to_the_given_stream_and_not_to_stdout(capsys) -> None:
    confirm_gate, _, out = gate(["n\n"])

    await confirm_gate.confirm(REQUEST)

    assert out.getvalue() == PROMPT
    assert capsys.readouterr().out == ""


async def test_default_stream_is_stderr(capsys) -> None:
    confirm_gate = CliConfirmGate("Viernes", timeout_s=5, lines=FakeLines(["n\n"]))

    await confirm_gate.confirm(REQUEST)

    captured = capsys.readouterr()
    assert captured.err == PROMPT
    assert captured.out == ""


async def test_concurrent_confirmations_are_serialized_prompt_by_prompt() -> None:
    confirm_gate, lines, out = gate(["s\n", "n\n"])

    first, second = await asyncio.gather(confirm_gate.confirm(REQUEST), confirm_gate.confirm(OTHER))

    assert (first, second) == (True, False)
    other_prompt = (
        'Viernes quiere ejecutar filesystem.delete con {"path": "b.md"}. ¿Confirmas? [s/N] '
    )
    assert lines.seen_output == [PROMPT, PROMPT + other_prompt]


async def test_stdin_lines_reads_one_line_per_call_and_signals_eof() -> None:
    lines = StdinLines(io.StringIO("s\nn\n"))

    assert await lines.readline() == "s\n"
    assert await lines.readline() == "n\n"
    assert await lines.readline() is None
    assert await lines.readline() is None


async def test_answer_typed_after_a_timeout_does_not_approve_the_next_prompt() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r")
    confirm_gate = CliConfirmGate(
        "Viernes", timeout_s=0.05, lines=StdinLines(stream), out=io.StringIO()
    )
    try:
        assert await confirm_gate.confirm(REQUEST) is False
        os.write(write_fd, b"s\n")
        await asyncio.sleep(0.1)

        assert await confirm_gate.confirm(OTHER) is False
    finally:
        os.close(write_fd)
        stream.close()


def test_timed_out_confirmation_does_not_block_loop_shutdown() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r")
    confirm_gate = CliConfirmGate(
        "Viernes", timeout_s=0.05, lines=StdinLines(stream), out=io.StringIO()
    )
    started = time.monotonic()
    try:
        assert asyncio.run(confirm_gate.confirm(REQUEST)) is False
    finally:
        os.close(write_fd)
        stream.close()

    assert time.monotonic() - started < 1
