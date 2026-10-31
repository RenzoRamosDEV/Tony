"""Expose the same declared native tools to CLI and API engines as to Claude."""

from __future__ import annotations

from typing import Any

from tony.core.mcp import ToolCatalog, ToolRef
from tony.core.runner.native_tools import NativeToolSet
from tony.core.runner.ports import EventSink


class PortableNativeTools:
    def __init__(self, names: list[str], handlers: Any, events: EventSink) -> None:
        self.tools = NativeToolSet(names, handlers, events)
        self.catalog = ToolCatalog.from_refs(
            ToolRef(
                "tony",
                tool.name,
                f"tony.{tool.name}",
                tool.description,
                tool.input_schema,
                False,
                False,
            )
            for tool in self.tools.sdk_tools
        )

    async def call(self, qualified: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self.tools.handler(qualified.removeprefix("tony."))(args)
