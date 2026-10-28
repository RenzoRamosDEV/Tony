"""Conversation mode of the runner: a persistent session for the front agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, McpSdkServerConfig, ResultMessage

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.claude_sdk import (
    BUILTIN_TOOLS,
    MCP_PREFIX,
    CanUseTool,
    assistant_text,
    make_can_use_tool,
    usage_from_message,
)
from tony.core.runner.front_prompt import build_front_system_prompt
from tony.core.runner.native_tools import SERVER_NAME, NativeToolHandlers, build_native_server
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolCaller, ToolProxyFactory
from tony.core.runner.reply_mode import FrontReply

FRONT_OWNER_ID = "front"


@dataclass(frozen=True)
class FrontTurn:
    text: str
    structured: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ConversationRunner(Protocol):
    session_id: str | None

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: NativeToolHandlers,
        events: EventSink,
    ) -> None: ...

    async def turn(self, prompt: str) -> FrontTurn: ...

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...


class SessionClient(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(self, prompt: str, session_id: str = "default") -> None: ...
    def receive_response(self) -> Any: ...
    async def interrupt(self) -> None: ...


def build_front_options(
    spec: AgentSpec,
    settings: TonySettings,
    native_server: McpSdkServerConfig,
    proxies: dict[str, McpSdkServerConfig],
    can_use_tool: CanUseTool,
    resume: str | None = None,
) -> ClaudeAgentOptions:
    servers = {SERVER_NAME: native_server, **proxies}
    return ClaudeAgentOptions(
        tools=[],
        allowed_tools=[f"{MCP_PREFIX}{server}__*" for server in servers],
        disallowed_tools=list(BUILTIN_TOOLS),
        system_prompt=build_front_system_prompt(spec, spec.tools.native),
        mcp_servers=servers,
        permission_mode="default",
        max_turns=spec.max_steps,
        model=settings.models[spec.model],
        can_use_tool=can_use_tool,
        setting_sources=[],
        strict_mcp_config=True,
        output_format={"type": "json_schema", "schema": FrontReply.model_json_schema()},
        include_partial_messages=False,
        resume=resume,
    )


class ClaudeSdkConversation:
    def __init__(
        self,
        settings: TonySettings,
        gate: ConfirmGate,
        call: ToolCaller,
        client_factory: Callable[[ClaudeAgentOptions], SessionClient] = ClaudeSDKClient,
    ) -> None:
        self._settings = settings
        self._gate = gate
        self._call = call
        self._client_factory = client_factory
        self._client: SessionClient | None = None
        self._options: ClaudeAgentOptions | None = None
        self._events: EventSink | None = None
        self.session_id: str | None = None

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: NativeToolHandlers,
        events: EventSink,
    ) -> None:
        limits = self._settings.limits
        proxies = ToolProxyFactory(
            catalog,
            self._call,
            self._gate,
            events,
            TaskState(FRONT_OWNER_ID),
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        ).build()
        self._options = build_front_options(
            spec,
            self._settings,
            build_native_server(spec.tools.native, handlers),
            proxies,
            make_can_use_tool(catalog),
        )
        self._events = events
        await self._connect(self._options)

    async def turn(self, prompt: str) -> FrontTurn:
        if self._client is None or self._options is None:
            raise RuntimeError("la sesión del front no está abierta")
        try:
            return await self._exchange(self._client, prompt)
        except Exception:
            if self.session_id is None:
                raise
        await self._reopen()
        assert self._client is not None
        return await self._exchange(self._client, prompt)

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()

    async def _connect(self, options: ClaudeAgentOptions) -> None:
        client = self._client_factory(options)
        await client.connect()
        self._client = client

    async def _reopen(self) -> None:
        assert self._options is not None
        try:
            await self.close()
        except Exception:  # noqa: BLE001 - the dead client may refuse to disconnect
            pass
        self._options.resume = self.session_id
        await self._connect(self._options)

    async def _exchange(self, client: SessionClient, prompt: str) -> FrontTurn:
        await client.query(prompt)
        last_text = ""
        final: ResultMessage | None = None
        async for message in client.receive_response():
            text = assistant_text(message)
            if text is not None:
                last_text = text
                if self._events is not None:
                    self._events.emit("assistant.text", {"text": text})
            if isinstance(message, ResultMessage):
                final = message
        if final is not None and final.session_id:
            self.session_id = final.session_id
        result_text = final.result if final is not None and final.result else None
        return FrontTurn(
            text=last_text or result_text or "",
            structured=final.structured_output if final is not None else None,
            usage=usage_from_message(final),
        )
