"""Task and turn expectations produce one message per unmet expectation (specs/evals)."""

from __future__ import annotations

from tony.core.evals.assertions import check_task, check_turn
from tony.core.evals.models import TaskExpect, TurnExpect
from tony.core.runner import TaskResult

OK = TaskResult(status="ok", resumen="Hay 3 ficheros .md")
EVENTS = [
    ("task.started", {}),
    ("tool.call", {"tool": "filesystem.list_directory", "args": {}}),
    ("tool.result", {"tool": "filesystem.list_directory", "ok": True}),
]


def test_everything_met_returns_no_messages() -> None:
    expect = TaskExpect(
        status="ok",
        tools_called_any=["filesystem.list_directory"],
        resumen_contains=["ficheros .md"],
    )

    assert check_task(OK, EVENTS, expect) == []


def test_status_mismatch_names_both() -> None:
    messages = check_task(OK, EVENTS, TaskExpect(status="partial"))

    assert len(messages) == 1 and "partial" in messages[0] and "ok" in messages[0]


def test_tools_called_any_without_match_lists_the_called_tools() -> None:
    expect = TaskExpect(status="ok", tools_called_any=["filesystem.read_file", "x.y"])

    messages = check_task(OK, EVENTS, expect)

    assert len(messages) == 1
    assert "filesystem.read_file" in messages[0] and "filesystem.list_directory" in messages[0]


def test_tools_called_all_names_each_missing_tool() -> None:
    expect = TaskExpect(
        status="ok", tools_called_all=["filesystem.list_directory", "filesystem.read_file", "a.b"]
    )

    messages = check_task(OK, EVENTS, expect)

    assert len(messages) == 2
    assert any("filesystem.read_file" in m for m in messages)
    assert any("a.b" in m for m in messages)
    assert not any("list_directory" in m for m in messages)


def test_resumen_contains_ignores_case() -> None:
    assert check_task(OK, EVENTS, TaskExpect(status="ok", resumen_contains=["HAY 3"])) == []
    messages = check_task(OK, EVENTS, TaskExpect(status="ok", resumen_contains=["cuatro"]))
    assert len(messages) == 1 and "cuatro" in messages[0]


def test_multiple_failures_are_all_reported() -> None:
    expect = TaskExpect(status="error", tools_called_any=["z.z"], resumen_contains=["nada"])

    assert len(check_task(OK, EVENTS, expect)) == 3


def test_turn_delegation_expectation() -> None:
    expected = check_turn("x", False, TurnExpect(delegates=True))
    unexpected = check_turn("x", True, TurnExpect(delegates=False))

    assert len(expected) == 1 and "delegaci" in expected[0] and "esperaba" in expected[0]
    assert len(unexpected) == 1 and "delegaci" in unexpected[0]
    assert check_turn("x", True, TurnExpect(delegates=True)) == []


def test_turn_reply_contains_is_case_insensitive() -> None:
    assert (
        check_turn("Son las 10:05, señor.", False, TurnExpect(reply_contains=[":", "SEÑOR"])) == []
    )
    messages = check_turn("Hola", False, TurnExpect(reply_contains=["adiós"]))
    assert len(messages) == 1 and "adiós" in messages[0]


def test_messages_are_exact() -> None:
    expect = TaskExpect(
        status="error",
        tools_called_any=["filesystem.read_file", "x.y"],
        tools_called_all=["a.b"],
        resumen_contains=["cuatro"],
    )

    assert check_task(OK, EVENTS, expect) == [
        "status esperado 'error', obtenido 'ok'",
        "ninguna de las tools ['filesystem.read_file', 'x.y'] fue llamada "
        "(llamadas: ['filesystem.list_directory'])",
        "la tool a.b no fue llamada",
        "'resumen' no contiene 'cuatro'",
    ]
    assert check_turn("Hola", False, TurnExpect(delegates=True, reply_contains=["adiós"])) == [
        "se esperaba una delegación al worker y no se produjo",
        "la respuesta no contiene 'adiós'",
    ]
    assert check_turn("x", True, TurnExpect()) == [
        "no se esperaba una delegación al worker y se produjo"
    ]
