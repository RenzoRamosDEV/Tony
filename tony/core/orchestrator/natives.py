from typing import Any

from tony.core.loader.skills import list_skills, read_skill_body
from tony.core.mcp.native import NativeFactory, NativeScope, NativeTool
from tony.core.orchestrator.ports import ToolReply

READ_SKILL_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Exact skill name."}},
    "required": ["name"],
}


def not_found(kind: str, name: str, available: list[str]) -> ToolReply:
    listed = ", ".join(available) or "none"
    return ToolReply(text=f"{kind} '{name}' not found; available: {listed}", is_error=True)


def read_skill(scope: NativeScope) -> NativeTool:
    async def run(args: dict[str, Any]) -> ToolReply:
        name = str(args.get("name", ""))
        body = read_skill_body(scope.root, scope.agent, name)
        if body is not None:
            return ToolReply(text=body)
        skills, _ = list_skills(scope.root, scope.agent)
        return not_found("skill", name, [skill.name for skill in skills])

    return NativeTool(
        description="Returns the instructions of one of your skills by its exact name.",
        input_schema=READ_SKILL_SCHEMA,
        run=run,
    )


def _not_ready(scope: NativeScope) -> NativeTool:
    async def run(args: dict) -> ToolReply:
        return ToolReply(text="not implemented", is_error=True)

    return NativeTool(description="", input_schema={"type": "object"}, run=run)


NATIVE_TOOLS: dict[str, NativeFactory] = {"read_skill": read_skill, "run_subagent": _not_ready}
