"""Builders for CLI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tony.core.loader import ToolConfig
from tony.core.mcp import McpServerStatus, ToolCallOutcome, ToolCatalog


def write_agent(
    agents_dir: Path,
    name: str,
    role: str = "worker",
    model: str = "claude-sonnet",
    engine: str | None = None,
) -> None:
    folder = agents_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    engine_line = f"engine: {engine}\n" if engine is not None else ""
    (folder / "agent.md").write_text(
        f"---\nname: {name}\nrole: {role}\nmodel: {model}\n{engine_line}---\nEres {name}.\n",
        encoding="utf-8",
    )


class FakeManager:
    def __init__(self, catalog: ToolCatalog | None = None) -> None:
        self.catalog = catalog or ToolCatalog.empty()
        self.started_with: ToolConfig | None = None
        self.server_filter: list[str] | None = None
        self.stopped = False
        self.statuses: dict[str, McpServerStatus] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start(self, tool_config: ToolConfig, server_filter: list[str] | None = None) -> None:
        self.started_with = tool_config
        self.server_filter = server_filter

    async def call(self, qualified: str, args: dict[str, Any], timeout: float) -> ToolCallOutcome:
        self.calls.append((qualified, args))
        if qualified in self.catalog:
            return ToolCallOutcome(ok=True, content=f"{qualified} ok", duration_ms=1)
        return ToolCallOutcome.failure("sin servidores")

    def status(self) -> dict[str, McpServerStatus]:
        return self.statuses

    async def stop(self) -> None:
        self.stopped = True
