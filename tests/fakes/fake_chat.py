import asyncio
from dataclasses import dataclass, field
from typing import Any

from tests.fakes.fake_engine import CallTool, ScriptError
from tony.core.orchestrator.ports import ChatOutcome, ProxiedTool, ToolReply, Usage


@dataclass(frozen=True)
class Say:
    """Streamed text chunks of the reply."""

    chunks: tuple[str, ...]

    def __init__(self, *chunks: str) -> None:
        object.__setattr__(self, "chunks", chunks)


@dataclass(frozen=True)
class Fail:
    error: Exception = field(default_factory=lambda: RuntimeError("model down"))


@dataclass(frozen=True)
class Wait:
    """Block until the event is set (or forever without one)."""

    event: asyncio.Event | None = None


ChatStep = Say | CallTool | Fail | Wait
DEFAULT_USAGE = Usage(3, 2)


class FakeChatEngine:
    """Scripted ChatEngine: one list of steps per turn; unscripted turns answer `ok`."""

    def __init__(self, *turns: list[ChatStep], usage: Usage = DEFAULT_USAGE) -> None:
        self._turns = [list(turn) for turn in turns]
        self._usage = usage
        self.system_prompts: list[str] = []
        self.prompts: list[str] = []
        self.offered: list[list[str]] = []
        self.model_ids: list[str] = []
        self.replies: list[ToolReply] = []

    async def converse(
        self, spec, system_prompt: str, prompt: str, tools: list[ProxiedTool], model_id, on_text
    ) -> ChatOutcome:
        self.system_prompts.append(system_prompt)
        self.prompts.append(prompt)
        self.offered.append([tool.id for tool in tools])
        self.model_ids.append(model_id)
        by_id = {tool.id: tool for tool in tools}
        steps = self._turns.pop(0) if self._turns else [Say("ok")]
        text: list[str] = []
        for step in steps:
            await self._run(step, by_id, text, on_text)
        return ChatOutcome(text="".join(text), usage=[self._usage])

    async def _run(self, step: ChatStep, by_id: dict[str, Any], text: list[str], on_text) -> None:
        if isinstance(step, Say):
            for chunk in step.chunks:
                on_text(chunk)
                text.append(chunk)
        elif isinstance(step, Fail):
            raise step.error
        elif isinstance(step, Wait):
            await (step.event or asyncio.Event()).wait()
        else:
            if step.tool_id not in by_id:
                raise ScriptError(f"scripted tool {step.tool_id} not offered: {list(by_id)}")
            self.replies.append(await by_id[step.tool_id].handler(step.args))
