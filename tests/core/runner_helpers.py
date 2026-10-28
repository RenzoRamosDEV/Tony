"""Builders shared by the runner tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import ResultMessage
from mcp.types import Tool, ToolAnnotations

from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog

ECHO_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def worker_spec(system_prompt: str = "Eres Viernes.", max_steps: int = 20) -> AgentSpec:
    return AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        max_steps=max_steps,
        system_prompt=system_prompt,
        path=Path("/tmp/viernes"),
    )


def mcp_tool(name: str, destructive: bool = False, schema: dict | None = None) -> Tool:
    return Tool(
        name=name,
        description=f"desc {name}",
        inputSchema=schema or {"type": "object", "properties": {}},
        annotations=ToolAnnotations(destructiveHint=True) if destructive else None,
    )


def fake_catalog(allow: list[str] | None = None, confirm: list[str] | None = None) -> ToolCatalog:
    tools = {"fake": [mcp_tool("echo", schema=ECHO_SCHEMA), mcp_tool("destroy", destructive=True)]}
    return ToolCatalog.build(tools, allow=allow, confirm=confirm or [])


def result_message(**overrides: Any) -> ResultMessage:
    fields: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 10,
        "duration_api_ms": 8,
        "is_error": False,
        "num_turns": 3,
        "session_id": "s",
        "total_cost_usd": 0.0123,
        "usage": {"input_tokens": 100, "output_tokens": 40},
        "result": "He listado los ficheros.",
        "structured_output": None,
    }
    fields.update(overrides)
    return ResultMessage(**fields)


class FakeClient:
    """Stands in for ClaudeSDKClient: scripted messages, optional hang, interrupt spy."""

    def __init__(
        self,
        messages: list[Any] | None = None,
        hang: bool = False,
        connect_delay: float = 0,
        exit_delay: float = 0,
    ) -> None:
        self.messages = messages or []
        self.hang = hang
        self.connect_delay = connect_delay
        self.exit_delay = exit_delay
        self.prompts: list[str] = []
        self.interrupts = 0
        self.before_messages: list[Any] = []

    async def __aenter__(self) -> FakeClient:
        await asyncio.sleep(self.connect_delay)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await asyncio.sleep(self.exit_delay)
        return None

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompts.append(prompt)

    async def receive_response(self):
        for action in self.before_messages:
            await action()
        if self.hang:
            await asyncio.Event().wait()
        for message in self.messages:
            yield message

    async def interrupt(self) -> None:
        self.interrupts += 1


class FailingClient(FakeClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def __aenter__(self) -> FakeClient:
        raise self.error
