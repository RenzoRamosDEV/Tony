from tony.core.events.messages import Ruling, ToolCall


class AllowAllGuard:
    async def decide(self, call: ToolCall) -> Ruling:
        return Ruling(verdict="allow", rule="allow_all")
