"""Expectation checks; each unmet expectation becomes one Spanish message."""

from __future__ import annotations

from typing import Any

from tony.core.evals.models import TaskExpect, TurnExpect
from tony.core.runner import TaskResult

Events = list[tuple[str, dict[str, Any]]]


def check_task(result: TaskResult, events: Events, expect: TaskExpect) -> list[str]:
    messages: list[str] = []
    if result.status != expect.status:
        messages.append(f"status esperado '{expect.status}', obtenido '{result.status}'")
    called = [payload.get("tool") for kind, payload in events if kind == "tool.call"]
    if expect.tools_called_any and not any(tool in called for tool in expect.tools_called_any):
        messages.append(
            f"ninguna de las tools {expect.tools_called_any} fue llamada (llamadas: {called})"
        )
    messages.extend(
        f"la tool {tool} no fue llamada" for tool in expect.tools_called_all if tool not in called
    )
    messages.extend(
        f"'resumen' no contiene '{text}'"
        for text in expect.resumen_contains
        if text.casefold() not in result.resumen.casefold()
    )
    return messages


def check_turn(reply: str, delegated: bool, expect: TurnExpect) -> list[str]:
    messages: list[str] = []
    if expect.delegates and not delegated:
        messages.append("se esperaba una delegación al worker y no se produjo")
    elif delegated and not expect.delegates:
        messages.append("no se esperaba una delegación al worker y se produjo")
    messages.extend(
        f"la respuesta no contiene '{text}'"
        for text in expect.reply_contains
        if text.casefold() not in reply.casefold()
    )
    return messages
