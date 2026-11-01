from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.ports import ToolReply

NATIVE_SERVER = "tony"

SubagentRunner = Callable[[str, TaskRequest], Awaitable[ToolReply]]


@dataclass(frozen=True)
class NativeTool:
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[ToolReply]]


@dataclass(frozen=True)
class NativeScope:
    """What a native tool knows about the agent run it is bound to."""

    root: Path
    agent: str
    run_subagent: SubagentRunner | None = None


NativeFactory = Callable[[NativeScope], NativeTool]
