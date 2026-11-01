import asyncio
from dataclasses import dataclass, field
from typing import Any

from tony.core.orchestrator.ports import EngineOutcome, ProxiedTool, ToolReply, Usage


class ScriptError(AssertionError):
    pass


@dataclass(frozen=True)
class CallTool:
    tool_id: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Final:
    text: str = ""
    structured: Any = None
    usage: Usage = Usage(10, 5)


@dataclass(frozen=True)
class Hang:
    pass


@dataclass(frozen=True)
class Raise:
    error: Exception


Step = CallTool | Final | Hang | Raise


class FakeModelEngine:
    """Scripted ModelEngine that drives the real proxied tool handlers."""

    def __init__(self, steps: list[Step]) -> None:
        self._steps = steps
        self.replies: list[ToolReply] = []
        self.offered: list[str] = []
        self.request = None
        self.spec = None
        self.model_id: str | None = None

    async def run(self, spec, request, tools: list[ProxiedTool], model_id: str) -> EngineOutcome:
        self.spec, self.request, self.model_id = spec, request, model_id
        self.offered = [tool.id for tool in tools]
        by_id = {tool.id: tool for tool in tools}
        for step in self._steps:
            if isinstance(step, Hang):
                await asyncio.Event().wait()
            if isinstance(step, Raise):
                raise step.error
            if isinstance(step, Final):
                return EngineOutcome(
                    text=step.text, structured=self._structured(step), usage=[step.usage]
                )
            if step.tool_id not in by_id:
                raise ScriptError(f"scripted tool {step.tool_id} not offered: {self.offered}")
            self.replies.append(await by_id[step.tool_id].handler(step.args))
        raise ScriptError("script ended without a Final step")

    def _structured(self, step: Final) -> Any:
        if callable(step.structured):
            return step.structured(self.replies)
        return step.structured


class ByAgentEngine:
    """ModelEngine running one FakeModelEngine script per agent, chosen by `spec.name`."""

    def __init__(self, scripts: dict[str, list[Step]]) -> None:
        self.engines = {name: FakeModelEngine(steps) for name, steps in scripts.items()}
        self.calls: list[str] = []

    async def run(self, spec, request, tools: list[ProxiedTool], model_id: str) -> EngineOutcome:
        self.calls.append(spec.name)
        if spec.name not in self.engines:
            raise ScriptError(f"no script for agent {spec.name}")
        return await self.engines[spec.name].run(spec, request, tools, model_id)
