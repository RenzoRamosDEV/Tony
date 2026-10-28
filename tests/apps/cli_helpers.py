"""Builders for CLI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tony.core.loader import ToolConfig
from tony.core.mcp import McpServerStatus, ToolCallOutcome, ToolCatalog


def write_agent(
    agents_dir: Path, name: str, role: str = "worker", model: str = "claude-sonnet"
) -> None:
    folder = agents_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "agent.md").write_text(
        f"---\nname: {name}\nrole: {role}\nmodel: {model}\n---\nEres {name}.\n", encoding="utf-8"
    )


class FakeManager:
    def __init__(self) -> None:
        self.catalog = ToolCatalog.empty()
        self.started_with: ToolConfig | None = None
        self.stopped = False
        self.statuses: dict[str, McpServerStatus] = {}

    async def start(self, tool_config: ToolConfig, server_filter: list[str] | None = None) -> None:
        self.started_with = tool_config

    async def call(self, qualified: str, args: dict[str, Any], timeout: float) -> ToolCallOutcome:
        return ToolCallOutcome.failure("sin servidores")

    def status(self) -> dict[str, McpServerStatus]:
        return self.statuses

    async def stop(self) -> None:
        self.stopped = True
