"""The manager port the worker side depends on, and the factory that builds the real one."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from tony.core.config import TonySettings
from tony.core.loader import ToolConfig
from tony.core.mcp.catalog import ToolCatalog
from tony.core.mcp.manager import McpManager
from tony.core.mcp.outcome import McpServerStatus, ToolCallOutcome


class ToolManager(Protocol):
    catalog: ToolCatalog

    async def start(
        self, tool_config: ToolConfig, server_filter: list[str] | None = None
    ) -> None: ...

    async def call(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome: ...

    def status(self) -> dict[str, McpServerStatus]: ...

    async def stop(self) -> None: ...


ManagerFactory = Callable[[TonySettings], ToolManager]


def default_manager_factory(settings: TonySettings) -> ToolManager:
    return McpManager(connect_timeout_s=settings.limits.mcp_connect_timeout_s)
