"""System and user prompts for a worker run."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from tony.core.loader import AgentSpec
from tony.core.runner.contracts import TaskRequest
from tony.core.skills import SkillSpec
from tony.core.skills.index import skills_index
from tony.core.skills.triggers import skill_blocks

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
    sections = [spec.system_prompt, context]
    if spec.skills:
        sections.append(skills_index(spec.skills))
    return "\n\n".join(sections)


def build_user_prompt(request: TaskRequest, skills: Sequence[SkillSpec] = ()) -> str:
    blocks = skill_blocks(f"{request.objetivo}\n{request.contexto}", skills)
    return blocks + USER_INSTRUCTION + request.model_dump_json()
