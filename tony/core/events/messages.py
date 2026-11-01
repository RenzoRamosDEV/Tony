from typing import Any, Literal

from pydantic import BaseModel, JsonValue, field_validator

Decision = Literal["allow", "confirm", "deny"]
UserDecision = Literal["allow", "deny", "timeout"]


class TaskRequest(BaseModel):
    objetivo: str
    contexto: str = ""
    restricciones: list[str] = []

    @field_validator("objetivo")
    @classmethod
    def _objetivo_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("objetivo must not be empty")
        return value


class TaskResult(BaseModel):
    resumen: str
    datos: JsonValue = None
    pasos: list[str] = []
    errores: list[str] = []


class ToolCall(BaseModel):
    task_id: str
    agent: str
    tool: str
    args: dict[str, Any]


class Ruling(BaseModel):
    verdict: Decision
    rule: str
    user_decision: UserDecision | None = None
