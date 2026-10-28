"""System and user prompts for a worker run."""

from __future__ import annotations

from datetime import datetime

from tony.core.loader import AgentSpec
from tony.core.runner.contracts import TaskRequest

USER_INSTRUCTION = "Resuelve la siguiente tarea y devuelve exclusivamente un TaskResult JSON.\n"


def format_moment(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def build_system_prompt(spec: AgentSpec, request: TaskRequest, now: datetime | None = None) -> str:
    moment = now or datetime.now().astimezone()
    restrictions = (
        "\n".join(f"  - {item}" for item in request.restricciones)
        if request.restricciones
        else "  - ninguna"
    )
    context = (
        "## Contexto de ejecución\n"
        f"- Fecha y hora: {format_moment(moment)}\n"
        f"- Rol: {spec.role}\n"
        f"- Restricciones:\n{restrictions}"
    )
    return f"{spec.system_prompt}\n\n{context}"


def build_user_prompt(request: TaskRequest) -> str:
    return USER_INSTRUCTION + request.model_dump_json()
