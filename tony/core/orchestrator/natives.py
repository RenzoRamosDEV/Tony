from typing import Any

from pydantic import ValidationError

from tony.core.events.messages import TaskRequest
from tony.core.loader.skills import list_skills, read_skill_body
from tony.core.mcp.native import NativeFactory, NativeScope, NativeTool
from tony.core.orchestrator.ports import ToolReply

READ_SKILL_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Exact skill name."}},
    "required": ["name"],
}

TAREA_SHAPE = "tarea must be an object {objetivo, contexto?, restricciones?}"
RUN_SUBAGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Exact subagent name."},
        "tarea": {
            "type": "object",
            "properties": {
                "objetivo": {"type": "string"},
                "contexto": {"type": "string"},
                "restricciones": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["objetivo"],
        },
    },
    "required": ["name", "tarea"],
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


def run_subagent(scope: NativeScope) -> NativeTool:
    async def run(args: dict[str, Any]) -> ToolReply:
        if scope.run_subagent is None:
            return ToolReply(text="subagents are not available here", is_error=True)
        tarea = args.get("tarea")
        if not isinstance(tarea, dict):
            return ToolReply(text=TAREA_SHAPE, is_error=True)
        try:
            request = TaskRequest.model_validate(tarea)
        except ValidationError as error:
            return ToolReply(text=f"invalid tarea: {_first_error(error)}", is_error=True)
        return await scope.run_subagent(str(args.get("name", "")), request)

    return NativeTool(
        description=(
            "Runs one of your subagents on a structured task and returns its result "
            "{resumen, datos, pasos, errores}."
        ),
        input_schema=RUN_SUBAGENT_SCHEMA,
        run=run,
    )


def _first_error(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{location}: {first['msg']}"


NATIVE_TOOLS: dict[str, NativeFactory] = {"read_skill": read_skill, "run_subagent": run_subagent}
