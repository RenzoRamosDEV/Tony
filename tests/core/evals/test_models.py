"""Eval definitions loaded from tareas.yaml and conversaciones.yaml (specs/evals)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.evals.loader import EvalLoadError, load_conversation_evals, load_task_evals
from tony.core.runner import TaskRequest

TASKS = """
- id: fs-list-md
  agent: viernes
  objetivo: lista los .md de notas
  contexto: ""
  restricciones: []
  expect:
    status: ok
    tools_called_any: [filesystem.list_directory]
    resumen_contains: [md]
- id: fs-write-rejected
  agent: viernes
  objetivo: escribe
  confirm: false
  expect:
    status: cancelled
"""
CONVERSATIONS = """
- id: hora
  turns:
    - user: "¿qué hora es?"
      expect:
        delegates: false
        reply_contains: [":"]
        judge: Responde la hora sin inventar datos
- id: saludo
  turns:
    - user: hola
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "evals.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_task_evals_are_loaded_with_defaults(tmp_path: Path) -> None:
    evals = load_task_evals(write(tmp_path, TASKS))

    assert [e.id for e in evals] == ["fs-list-md", "fs-write-rejected"]
    first = evals[0]
    assert first.agent == "viernes"
    assert first.request() == TaskRequest(objetivo="lista los .md de notas")
    assert first.expect.status == "ok"
    assert first.expect.tools_called_any == ["filesystem.list_directory"]
    assert first.expect.tools_called_all == []
    assert first.expect.resumen_contains == ["md"]
    assert first.confirm is True
    assert evals[1].confirm is False and evals[1].expect.status == "cancelled"


def test_duplicate_task_id_is_rejected(tmp_path: Path) -> None:
    text = TASKS.replace("id: fs-write-rejected", "id: fs-list-md")

    with pytest.raises(EvalLoadError, match="fs-list-md"):
        load_task_evals(write(tmp_path, text))


@pytest.mark.parametrize("missing", ["id", "agent", "objetivo"])
def test_task_without_required_fields_is_rejected(tmp_path: Path, missing: str) -> None:
    text = TASKS.replace(f"{missing}:", f"{missing}_x:", 1)

    with pytest.raises(EvalLoadError, match=missing):
        load_task_evals(write(tmp_path, text))


def test_task_with_unknown_field_or_status_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvalLoadError, match="extra"):
        load_task_evals(write(tmp_path, TASKS.replace("contexto:", "extra: 1\n  contexto:")))
    with pytest.raises(EvalLoadError, match="status"):
        load_task_evals(write(tmp_path, TASKS.replace("status: ok", "status: fine")))


def test_file_must_be_a_list(tmp_path: Path) -> None:
    with pytest.raises(EvalLoadError, match="lista"):
        load_task_evals(write(tmp_path, "id: x\n"))
    with pytest.raises(EvalLoadError, match="no existe"):
        load_task_evals(tmp_path / "nadie.yaml")


def test_conversation_evals_are_loaded(tmp_path: Path) -> None:
    evals = load_conversation_evals(write(tmp_path, CONVERSATIONS))

    assert [e.id for e in evals] == ["hora", "saludo"]
    turn = evals[0].turns[0]
    assert turn.user == "¿qué hora es?"
    assert turn.expect.delegates is False and turn.expect.reply_contains == [":"]
    assert turn.expect.judge == "Responde la hora sin inventar datos"
    plain = evals[1].turns[0].expect
    assert plain.delegates is False and plain.reply_contains == [] and plain.judge is None


def test_conversation_without_turns_or_with_duplicate_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvalLoadError, match="turns"):
        load_conversation_evals(write(tmp_path, "- id: x\n"))
    with pytest.raises(EvalLoadError, match="hora"):
        load_conversation_evals(write(tmp_path, CONVERSATIONS.replace("id: saludo", "id: hora")))


def test_error_messages_name_the_file_and_entry(tmp_path: Path) -> None:
    import pytest as _pytest

    with _pytest.raises(EvalLoadError) as duplicate:
        load_task_evals(write(tmp_path, TASKS.replace("id: fs-write-rejected", "id: fs-list-md")))
    assert str(duplicate.value) == "evals.yaml: id duplicado 'fs-list-md'"

    with _pytest.raises(EvalLoadError) as missing_id:
        load_task_evals(write(tmp_path, TASKS.replace("id:", "id_x:", 1)))
    assert str(missing_id.value).startswith("evals.yaml [#1]: id")

    with _pytest.raises(EvalLoadError) as bad_status:
        load_task_evals(write(tmp_path, TASKS.replace("status: ok", "status: fine")))
    assert str(bad_status.value).startswith("evals.yaml [fs-list-md]: expect.status")

    with _pytest.raises(EvalLoadError) as not_list:
        load_task_evals(write(tmp_path, "id: x\n"))
    assert str(not_list.value) == "evals.yaml: debe ser una lista de evals"

    with _pytest.raises(EvalLoadError) as bad_yaml:
        load_task_evals(write(tmp_path, "- id: [\n"))
    assert str(bad_yaml.value).startswith("evals.yaml: YAML inválido: ")

    with _pytest.raises(EvalLoadError) as missing_file:
        load_task_evals(tmp_path / "nadie.yaml")
    assert str(missing_file.value) == f"no existe {tmp_path / 'nadie.yaml'}"


def test_request_carries_context_and_restrictions(tmp_path: Path) -> None:
    text = TASKS.replace('contexto: ""', "contexto: c").replace(
        "restricciones: []", "restricciones: [r]"
    )

    first = load_task_evals(write(tmp_path, text))[0]

    assert first.request() == TaskRequest(
        objetivo="lista los .md de notas", contexto="c", restricciones=["r"]
    )
