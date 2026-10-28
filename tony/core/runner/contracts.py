"""Structured task contract between the orchestrating side and a worker agent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

TaskStatus = Literal["ok", "partial", "error", "cancelled", "timeout"]


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objetivo: str
    contexto: str = ""
    restricciones: list[str] = []


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    resumen: str
    datos: dict[str, Any] | list[Any] | str | None = None
    pasos: list[str] = []
    errores: list[str] = []
