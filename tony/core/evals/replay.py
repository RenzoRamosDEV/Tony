"""Runners that reproduce a recorded fixture: no model, no tools, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.conversation import FrontTurn

TASK_RESULT = "task.result"
REPLAYED_EVENTS = frozenset(
    {"task.started", "assistant.text", "tool.call", "tool.result", "task.finished"}
)
MISSING_FIXTURE = (
    "no existe el fixture {path}; grábalo con `TONY_EVALS=1 uv run pytest evals/ -m evals` y "
    "conviértelo con `tony replay evals/runs/<fecha>/{id}.jsonl --to-eval {id}`"
)


class FixtureMissing(Exception):
    pass


def read_fixture(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FixtureMissing(MISSING_FIXTURE.format(path=path, id=path.stem))
    lines: list[dict[str, Any]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise FixtureMissing(f"{path}: la línea {number} no es JSON: {exc}") from None
    return lines


class ReplayRunner:
    """AgentRunner that re-emits the recorded runner events and returns the recorded result."""

    def __init__(self, fixture: Path) -> None:
        self._fixture = fixture
        self.events = read_fixture(fixture)

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        result: TaskResult | None = None
        for event in self.events:
            kind, payload = event.get("type"), event.get("payload", {})
            if kind == TASK_RESULT:
                result = TaskResult.model_validate(payload["result"])
            elif kind in REPLAYED_EVENTS:
                events.emit(kind, payload)
        if result is None:
            raise FixtureMissing(f"{self._fixture}: el fixture no termina con {TASK_RESULT}")
        return result


class ReplayConversationRunner:
    """ConversationRunner that answers each turn from the fixture, delegating when recorded."""

    session_id: str | None = "replay"

    def __init__(self, fixture: Path) -> None:
        self._fixture = fixture
        self.turns = read_fixture(fixture)
        self._handlers: Any = None
        self._next = 0

    def task_results(self) -> dict[str, TaskResult]:
        """Recorded worker result per delegated `objetivo`, for a fake worker to return."""
        return {
            turn["delegate"]["objetivo"]: TaskResult.model_validate(turn["task_result"])
            for turn in self.turns
            if turn.get("delegate") and turn.get("task_result")
        }

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: Any,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        self._handlers = handlers

    async def turn(self, prompt: str) -> FrontTurn:
        number = self._next + 1
        if self._next >= len(self.turns):
            raise FixtureMissing(f"{self._fixture}: no hay turno {number} grabado")
        recorded = self.turns[self._next]
        self._next += 1
        if recorded.get("delegate"):
            await self._handlers.delegate(TaskRequest.model_validate(recorded["delegate"]))
        reply = recorded["reply"]
        return FrontTurn(text=str(reply.get("display_text", "")), structured=reply)

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        return None
