from tony.core.events.messages import Decision, ToolCall


class AllowAllGuard:
    async def decide(self, call: ToolCall) -> Decision:
        return "allow"
