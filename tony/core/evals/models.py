"""Eval definitions: tasks (evals/tareas.yaml) and conversations (evals/conversaciones.yaml)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from tony.core.runner import TaskRequest
from tony.core.runner.contracts import TaskStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskExpect(StrictModel):
    status: TaskStatus
    tools_called_any: list[str] = []
    tools_called_all: list[str] = []
    resumen_contains: list[str] = []


class TaskEval(StrictModel):
    id: str
    agent: str
    objetivo: str
    contexto: str = ""
    restricciones: list[str] = []
    confirm: bool = True
    """Answer given to every confirmation the task asks for."""
    expect: TaskExpect

    def request(self) -> TaskRequest:
        return TaskRequest(
            objetivo=self.objetivo, contexto=self.contexto, restricciones=self.restricciones
        )


class TurnExpect(StrictModel):
    delegates: bool = False
    reply_contains: list[str] = []
    judge: str | None = None


class Turn(StrictModel):
    user: str
    expect: TurnExpect = TurnExpect()


class ConversationEval(StrictModel):
    id: str
    turns: list[Turn]
