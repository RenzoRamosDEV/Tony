"""ConversationRunner double with scripted turns; a turn may call the native handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink
from tony.core.runner.conversation import FrontTurn, TextCallback
from tony.core.runner.native_tools import NativeToolHandlers

ScriptedTurn = str | dict[str, Any] | FrontTurn | Callable[[str, Any], Awaitable[Any]]
DEFAULT_TEXT = "Sin guion."
SPEECH_CHUNK_PAUSE_S = 0.05
BLOCK_UNTIL_INTERRUPT = "block_until_interrupt"
INTERRUPTED_ERROR = "error_during_execution: interrupted"


def interruptible(*chunks: str) -> dict[str, Any]:
    """A turn that streams `chunks` as display text, then hangs until `interrupt()`; the
    SDK then answers with an error result, as the real one does."""
    return {"display_text": "", "chunks": list(chunks), BLOCK_UNTIL_INTERRUPT: True}


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
        self.resumes: list[str | None] = []
        self.fail_resume = False
        self.prompts: list[str] = []
        self.interrupts = 0
        self.closed = False
        self._interrupted = asyncio.Event()

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: NativeToolHandlers,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        self.resumes.append(resume)
        if resume is not None and self.fail_resume:
            raise RuntimeError("no such session")
        self.handlers = handlers
        self.opened.append(spec)

    async def turn(
        self,
        prompt: str,
        on_text: TextCallback | None = None,
        on_speech: TextCallback | None = None,
    ) -> FrontTurn:
        self.prompts.append(prompt)
        self._interrupted.clear()
        item: Any = self.turns.pop(0) if self.turns else DEFAULT_TEXT
        if callable(item):
            item = await item(prompt, self.handlers)
        turn = to_front_turn(item)
        structured = turn.structured or {}
        if on_text is not None:
            for chunk in structured.get("chunks", []):
                await on_text(chunk)
        if on_speech is not None:
            # A real model streams over time; the pause lets the speech pipeline keep up.
            for chunk in structured.get("speech_chunks", []):
                await on_speech(chunk)
                await asyncio.sleep(SPEECH_CHUNK_PAUSE_S)
        if structured.get(BLOCK_UNTIL_INTERRUPT):
            await self._interrupted.wait()
            return FrontTurn(text="", structured=None, error=INTERRUPTED_ERROR)
        return turn

    async def interrupt(self) -> None:
        self.interrupts += 1
        self._interrupted.set()

    async def close(self) -> None:
        self.closed = True
