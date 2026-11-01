from tony.core.mcp.native import NativeFactory, NativeScope, NativeTool
from tony.core.orchestrator.ports import ToolReply


def _not_ready(scope: NativeScope) -> NativeTool:
    async def run(args: dict) -> ToolReply:
        return ToolReply(text="not implemented", is_error=True)

    return NativeTool(description="", input_schema={"type": "object"}, run=run)


NATIVE_TOOLS: dict[str, NativeFactory] = {"read_skill": _not_ready, "run_subagent": _not_ready}
