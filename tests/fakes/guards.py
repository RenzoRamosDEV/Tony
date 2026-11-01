from tony.core.events.messages import Ruling, ToolCall

ALLOW = Ruling(verdict="allow", rule="test/allow")


class RecordingGuard:
    def __init__(self, ruling: Ruling = ALLOW) -> None:
        self.ruling = ruling
        self.calls: list[ToolCall] = []

    async def decide(self, call: ToolCall) -> Ruling:
        self.calls.append(call)
        return self.ruling
