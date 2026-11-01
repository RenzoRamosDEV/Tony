from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from tony.core.events.messages import TaskRequest
from tony.core.loader.agent_md import AgentSpec


@dataclass(frozen=True)
class ToolReply:
    text: str
    is_error: bool = False


ToolHandler = Callable[[dict[str, Any]], Awaitable[ToolReply]]


@dataclass(frozen=True)
class ProxiedTool:
    id: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EngineOutcome:
    text: str
    structured: Any = None
    usage: list[Usage] = field(default_factory=list)


class ModelEngine(Protocol):
    async def run(
        self,
        spec: AgentSpec,
        request: TaskRequest,
        tools: list[ProxiedTool],
        model_id: str,
    ) -> EngineOutcome: ...


@dataclass(frozen=True)
class ChatOutcome:
    text: str
    usage: list[Usage] = field(default_factory=list)


TextCallback = Callable[[str], None]


class ChatEngine(Protocol):
    async def converse(
        self,
        spec: AgentSpec,
        system_prompt: str,
        prompt: str,
        tools: list[ProxiedTool],
        model_id: str,
        on_text: TextCallback,
    ) -> ChatOutcome: ...


class EventSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...
