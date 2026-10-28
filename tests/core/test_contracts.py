"""Tests for TaskRequest / TaskResult contracts (specs/agent-runner)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tony.core.runner import TaskRequest, TaskResult


def test_task_request_defaults_and_serialization() -> None:
    request = TaskRequest(objetivo="lista los .md")

    assert request.contexto == ""
    assert request.restricciones == []
    assert json.loads(request.model_dump_json()) == {
        "objetivo": "lista los .md",
        "contexto": "",
        "restricciones": [],
    }


def test_task_request_requires_objetivo() -> None:
    with pytest.raises(ValidationError):
        TaskRequest()


@pytest.mark.parametrize("status", ["ok", "partial", "error", "cancelled", "timeout"])
def test_task_result_accepts_every_status(status: str) -> None:
    assert TaskResult(status=status, resumen="r").status == status


def test_task_result_rejects_status_outside_domain() -> None:
    with pytest.raises(ValidationError):
        TaskResult(status="done", resumen="r")


def test_task_result_defaults() -> None:
    result = TaskResult(status="ok", resumen="r")

    assert result.model_dump() == {
        "status": "ok",
        "resumen": "r",
        "datos": None,
        "pasos": [],
        "errores": [],
    }


@pytest.mark.parametrize("datos", [{"a": 1}, [1, 2], "texto", None])
def test_task_result_datos_accepts_dict_list_str_or_null(datos) -> None:
    assert TaskResult(status="ok", resumen="r", datos=datos).datos == datos


def test_task_result_rejects_numeric_datos() -> None:
    with pytest.raises(ValidationError):
        TaskResult(status="ok", resumen="r", datos=3)


def test_task_result_schema_is_json_serializable_with_required_fields() -> None:
    schema = TaskResult.model_json_schema()

    assert json.loads(json.dumps(schema)) == schema
    assert set(schema["properties"]) == {"status", "resumen", "datos", "pasos", "errores"}
    assert schema["properties"]["status"]["enum"] == [
        "ok",
        "partial",
        "error",
        "cancelled",
        "timeout",
    ]
