"""Model-based judge for conversation replies: a fixed prompt and a {pass, reason} verdict."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

JUDGE_PROMPT = (
    "Eres un juez estricto de un asistente personal en español. Evalúa si la RESPUESTA cumple "
    "el CRITERIO. No premies la cortesía; penaliza datos inventados.\n\n"
    "CRITERIO: {criterion}\n\nRESPUESTA:\n{reply}\n\n"
    'Devuelve solo un objeto JSON {{"pass": true|false, "reason": "<motivo breve>"}}.'
)
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
}
INVALID_VERDICT = "respuesta del juez no válida"

OneShot = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str


async def judge(one_shot: OneShot, criterion: str, reply: str) -> Verdict:
    try:
        answer = await one_shot(JUDGE_PROMPT.format(criterion=criterion, reply=reply), JUDGE_SCHEMA)
    except Exception as exc:  # noqa: BLE001 - a judge failure is a failed verdict, not a crash
        return Verdict(False, f"{INVALID_VERDICT}: {exc}")
    return _parse(answer)


def _parse(answer: Any) -> Verdict:
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except json.JSONDecodeError:
            return Verdict(False, INVALID_VERDICT)
    if not isinstance(answer, dict) or not isinstance(answer.get("pass"), bool):
        return Verdict(False, INVALID_VERDICT)
    return Verdict(bool(answer["pass"]), str(answer.get("reason", "")))
