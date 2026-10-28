"""Wraps a live ConversationRunner and writes one fixture line per turn."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.conversation import ConversationRunner, FrontTurn
from tony.core.runner.front_prompt import PREAMBLE_END


class _RecordingHandlers:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.delegate_request: TaskRequest | None = None
        self.delegate_result: TaskResult | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def delegate(self, request: TaskRequest) -> TaskResult:
        self.delegate_request = request
        self.delegate_result = await self._inner.delegate(request)
        return self.delegate_result

    def reset(self) -> None:
        self.delegate_request = None
        self.delegate_result = None


class RecordingConversationRunner:
    def __init__(self, inner: ConversationRunner, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._handlers: _RecordingHandlers | None = None
        self._turns = 0

    @property
    def session_id(self) -> str | None:
        return self._inner.session_id

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: Any,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        self._handlers = _RecordingHandlers(handlers)
        self._truncate()
        await self._inner.open(spec, catalog, self._handlers, events, resume=resume)

    async def turn(self, prompt: str) -> FrontTurn:
        assert self._handlers is not None, "open() must run before turn()"
        self._handlers.reset()
        turn = await self._inner.turn(prompt)
        self._turns += 1
        self._write(
            {
                "turn": self._turns,
                "user": _user_text(prompt),
                "delegate": _dump(self._handlers.delegate_request),
                "task_result": _dump(self._handlers.delegate_result),
                "reply": turn.structured or {"display_text": turn.text, "speech_text": None},
            }
        )
        return turn

    async def interrupt(self) -> None:
        await self._inner.interrupt()

    async def close(self) -> None:
        await self._inner.close()

    def _truncate(self) -> None:
        # One run per file: a re-recorded conversation replaces the previous run.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("", encoding="utf-8")

    def _write(self, line: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(line, ensure_ascii=False) + "\n")


def _user_text(prompt: str) -> str:
    _, marker, rest = prompt.rpartition(PREAMBLE_END)
    return rest.lstrip("\n") if marker else prompt


def _dump(model: Any) -> dict[str, Any] | None:
    return model.model_dump() if model is not None else None
