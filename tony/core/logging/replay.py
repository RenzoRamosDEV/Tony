"""Read a task JSONL, render it for humans and derive an eval entry plus its fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

Event = dict[str, Any]
INCOMPLETE_REQUEST = (
    "petición incompleta en el registro: task.started no incluye contexto ni "
    "restricciones; revisa la entrada generada"
)


class ReplayError(Exception):
    pass


def read_events(path: Path) -> list[Event]:
    if not path.is_file():
        raise ReplayError(f"no existe {path}")
    events: list[Event] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReplayError(f"{path}: la línea {number} no es JSON: {exc}") from None
        if not isinstance(event, dict):
            raise ReplayError(f"{path}: la línea {number} no es un objeto JSON")
        events.append(event)
    return events


def render_events(events: list[Event]) -> str:
    return "\n".join(_render(event) for event in events)


def _render(event: Event) -> str:
    kind = str(event.get("type", "?"))
    payload = event.get("payload") or {}
    time = str(event.get("ts", ""))[11:19]
    head = f"{event.get('seq', '?'):>3} {time} {kind}"
    return f"{head} {_detail(kind, payload)}".rstrip()


def _detail(kind: str, payload: dict[str, Any]) -> str:
    if kind == "tool.call":
        return f"{payload.get('tool')} {_json(payload.get('args', {}))}"
    if kind == "tool.result":
        state = "ok" if payload.get("ok") else f"error: {payload.get('error')}"
        return f"{payload.get('tool')} {state} ({payload.get('duration_ms', 0)} ms)"
    if kind == "task.finished":
        usage = payload.get("usage") or {}
        tokens = f"{usage.get('input_tokens', 0)}/{usage.get('output_tokens', 0)}"
        return (
            f"status={payload.get('status')} tokens {tokens} "
            f"coste ${usage.get('total_cost_usd', 0)}"
        )
    if kind == "task.result":
        result = payload.get("result") or {}
        return f"status: {result.get('status')} — {result.get('resumen', '')}"
    if kind == "assistant.text":
        return str(payload.get("text", "")).replace("\n", " ")[:120]
    return _json(payload) if payload else ""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def to_eval(events: list[Event], eval_id: str) -> tuple[str, list[str], list[str]]:
    """YAML entry for tareas.yaml, the fixture lines derived from a task log, and warnings."""
    started = _first(events, "task.started")
    if started is None:
        raise ReplayError("el registro no contiene task.started")
    result = _first(events, "task.result")
    if result is None:
        raise ReplayError("el registro no contiene task.result")
    queued = _first(events, "task.queued") or {}
    tools: list[str] = []
    for event in events:
        if event.get("type") == "tool.call":
            tool = str((event.get("payload") or {}).get("tool"))
            if tool not in tools:
                tools.append(tool)
    entry = {
        "id": eval_id,
        "agent": started.get("agent"),
        "objetivo": queued.get("objetivo", started.get("objetivo", "")),
        "contexto": started.get("contexto", ""),
        "restricciones": list(started.get("restricciones", [])),
        "expect": {"status": (result.get("result") or {}).get("status"), "tools_called_all": tools},
    }
    yaml_entry = yaml.safe_dump([entry], allow_unicode=True, sort_keys=False)
    warnings = [] if _carries_request(started) else [INCOMPLETE_REQUEST]
    return yaml_entry, [json.dumps(event, ensure_ascii=False) for event in events], warnings


def _carries_request(started: dict[str, Any]) -> bool:
    return "contexto" in started and "restricciones" in started


def _first(events: list[Event], kind: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == kind:
            return dict(event.get("payload") or {})
    return None
