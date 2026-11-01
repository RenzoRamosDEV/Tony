from typing import Any

from tony.core.orchestrator.ports import ToolReply

OK = ToolReply(text="ok")


class FakeToolCaller:
    def __init__(self, reply: ToolReply = OK) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        self.calls.append((tool_id, args))
        return self.reply
