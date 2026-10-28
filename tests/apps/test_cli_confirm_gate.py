"""Tests for the interactive CLI confirmation gate."""

from __future__ import annotations

import asyncio

import pytest

from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.core.mcp import ConfirmRequest

REQUEST = ConfirmRequest.create("t", "filesystem.write_file", {"path": "a.md"})


class RecordingReader:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


@pytest.mark.parametrize("answer", ["Sí", "si", "s", "S", " sí ", "SI"])
async def test_affirmative_answers_approve(answer: str) -> None:
    gate = CliConfirmGate("Viernes", timeout_s=5, reader=RecordingReader(answer))

    assert await gate.confirm(REQUEST) is True


@pytest.mark.parametrize("answer", ["n", "", "no", "yes", "sí claro", "y"])
async def test_other_answers_reject(answer: str) -> None:
    gate = CliConfirmGate("Viernes", timeout_s=5, reader=RecordingReader(answer))

    assert await gate.confirm(REQUEST) is False


async def test_timeout_rejects() -> None:
    def never_answers(prompt: str) -> str:
        import time

        time.sleep(0.5)
        return "s"

    gate = CliConfirmGate("Viernes", timeout_s=0.05, reader=never_answers)

    assert await gate.confirm(REQUEST) is False


async def test_prompt_text_names_agent_tool_and_args() -> None:
    reader = RecordingReader("n")
    gate = CliConfirmGate("Viernes", timeout_s=5, reader=reader)

    await gate.confirm(REQUEST)

    assert reader.prompts == [
        'Viernes quiere ejecutar filesystem.write_file con {"path": "a.md"}. ¿Confirmas? [s/N] '
    ]


async def test_reader_runs_off_the_event_loop() -> None:
    loop_was_free = asyncio.Event()

    def blocking_reader(prompt: str) -> str:
        import time

        time.sleep(0.1)
        return "s"

    async def mark_free() -> None:
        await asyncio.sleep(0.01)
        loop_was_free.set()

    gate = CliConfirmGate("Viernes", timeout_s=5, reader=blocking_reader)
    result, _ = await asyncio.gather(gate.confirm(REQUEST), mark_free())

    assert result is True
    assert loop_was_free.is_set()
