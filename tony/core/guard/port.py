from typing import Protocol, runtime_checkable

from tony.core.events.messages import Ruling, ToolCall


@runtime_checkable
class Guard(Protocol):
    async def decide(self, call: ToolCall) -> Ruling: ...
