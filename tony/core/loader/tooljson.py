"""Edits of agents/<agent>/tool/tool.json that preserve everything they do not touch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tony.core.config.atomic import write_atomic

ToolJson = dict[str, Any]


class ToolJsonError(Exception):
    pass


def read_tool_json(path: Path) -> ToolJson:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolJsonError(f"tool.json inválido: {exc}") from None
    if not isinstance(data, dict):
        raise ToolJsonError("tool.json: debe ser un objeto JSON")
    return data


def upsert_server(
    data: ToolJson,
    name: str,
    server: dict[str, Any],
    allow: list[str] | None = None,
    confirm: list[str] | None = None,
    force: bool = False,
) -> ToolJson:
    servers = data.setdefault("mcpServers", {})
    if name in servers and not force:
        raise ToolJsonError(f"el servidor '{name}' ya existe; usa --force para sustituirlo")
    servers[name] = server
    for key, values in (("allow", allow), ("confirm", confirm)):
        if values:
            current = list(data.get(key) or [])
            data[key] = current + [v for v in values if v not in current]
    return data


def remove_server(data: ToolJson, name: str) -> ToolJson:
    servers = data.get("mcpServers") or {}
    if name not in servers:
        raise ToolJsonError(f"el servidor '{name}' no existe en mcpServers")
    del servers[name]
    return data


def write_tool_json(path: Path, data: ToolJson) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
