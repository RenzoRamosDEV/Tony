from tony.core.events.messages import Decision, ToolCall


class RecordingGuard:
    def __init__(self, decision: Decision = "allow") -> None:
        self.decision = decision
        self.calls: list[ToolCall] = []

    async def decide(self, call: ToolCall) -> Decision:
        self.calls.append(call)
        return self.decision
