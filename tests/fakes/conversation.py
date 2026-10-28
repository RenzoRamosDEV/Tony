"""ConversationRunner double with scripted turns; a turn may call the native handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink
from tony.core.runner.conversation import FrontTurn
from tony.core.runner.native_tools import NativeToolHandlers

ScriptedTurn = str | dict[str, Any] | FrontTurn | Callable[[str, Any], Awaitable[Any]]
DEFAULT_TEXT = "Sin guion."


def to_front_turn(item: Any) -> FrontTurn:
    if isinstance(item, FrontTurn):
        return item
    if isinstance(item, dict):
        return FrontTurn(text=str(item.get("display_text", "")), structured=item)
    return FrontTurn(text=str(item), structured=None)


class FakeConversationRunner:
    def __init__(self, turns: list[ScriptedTurn], session_id: str = "fake-session") -> None:
        self.turns = list(turns)
        self.session_id: str | None = session_id
        self.handlers: NativeToolHandlers | None = None
        self.opened: list[AgentSpec] = []
        self.prompts: list[str] = []
        self.interrupts = 0
        self.closed = False

    async def open(
        self, spec: AgentSpec, catalog: ToolCatalog, handlers: NativeToolHandlers, events: EventSink
    ) -> None:
        self.handlers = handlers
        self.opened.append(spec)

    async def turn(self, prompt: str) -> FrontTurn:
        self.prompts.append(prompt)
        item: Any = self.turns.pop(0) if self.turns else DEFAULT_TEXT
        if callable(item):
            item = await item(prompt, self.handlers)
        return to_front_turn(item)

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def close(self) -> None:
        self.closed = True
