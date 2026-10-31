"""Conversation mode of the runner: a persistent session for the front agent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, McpSdkServerConfig, ResultMessage
from claude_agent_sdk.types import StreamEvent

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.auth import claude_account_options
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
from tony.core.runner.partial_json import PartialJsonFieldExtractor
from tony.core.runner.ports import EventSink
from tony.core.runner.proxy import TaskState, ToolCaller, ToolProxyFactory
from tony.core.runner.reply_mode import FrontReply

FRONT_OWNER_ID = "front"
FRONT_EFFORT = "low"
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"
TextCallback = Callable[[str], Awaitable[None]]
TURN_ERROR = "turn.error"
TURN_LOST = (
    "No pude completar el turno: se perdió la conexión con el modelo y el resultado de "
    "las acciones ya iniciadas es desconocido; no las repitas sin comprobarlo. "
    "Diagnóstico: {diagnostic}"
)
TURN_FAILED = (
    "No pude completar el turno: el modelo terminó con un error. Diagnóstico: {diagnostic}"
)


@dataclass(frozen=True)
class FrontTurn:
    text: str
    structured: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class ConversationRunner(Protocol):
    session_id: str | None

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: NativeToolHandlers,
        events: EventSink,
        resume: str | None = None,
    ) -> None: ...

    async def turn(
        self,
        prompt: str,
        on_text: TextCallback | None = None,
        on_speech: TextCallback | None = None,
    ) -> FrontTurn: ...

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
        **claude_account_options(settings.engines[spec.engine]),
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
        include_partial_messages=True,
        effort=FRONT_EFFORT,
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
        self._dead = False
        self._turn_state = TaskState(FRONT_OWNER_ID)
        self.session_id: str | None = None

    @property
    def turn_state(self) -> TaskState:
        return self._turn_state

    async def open(
        self,
        spec: AgentSpec,
        catalog: ToolCatalog,
        handlers: NativeToolHandlers,
        events: EventSink,
        resume: str | None = None,
    ) -> None:
        limits = self._settings.limits
        proxies = ToolProxyFactory(
            catalog,
            self._call,
            self._gate,
            events,
            lambda: self._turn_state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        ).build()
        self._options = build_front_options(
            spec,
            self._settings,
            build_native_server(spec.tools.native, handlers, events),
            proxies,
            make_can_use_tool(catalog),
            resume=resume,
        )
        self._events = events
        await self._connect(self._options)

    async def turn(
        self,
        prompt: str,
        on_text: TextCallback | None = None,
        on_speech: TextCallback | None = None,
    ) -> FrontTurn:
        client = await self._live_client()
        self._turn_state = TaskState(FRONT_OWNER_ID, interrupt=self.interrupt)
        try:
            await client.query(prompt)
        except Exception:
            if self.session_id is None:
                raise
            client = await self._reopen()
            await client.query(prompt)
        try:
            return await self._receive(client, _ReplyStream(on_text, on_speech))
        except Exception as exc:  # noqa: BLE001 - the prompt is out: never resend it
            self._dead = True
            return self._failed_turn(TURN_LOST, f"{exc.__class__.__name__}: {exc}", None)

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.disconnect()

    async def _live_client(self) -> SessionClient:
        if self._client is None or self._options is None:
            raise RuntimeError("la sesión del front no está abierta")
        if self._dead:
            return await self._reopen()
        return self._client

    async def _connect(self, options: ClaudeAgentOptions) -> SessionClient:
        client = self._client_factory(options)
        await client.connect()
        self._client = client
        self._dead = False
        return client

    async def _reopen(self) -> SessionClient:
        assert self._options is not None
        try:
            await self.close()
        except Exception:  # noqa: BLE001 - the dead client may refuse to disconnect
            pass
        self._options.resume = self.session_id
        return await self._connect(self._options)

    async def _receive(self, client: SessionClient, stream: _ReplyStream) -> FrontTurn:
        last_text = ""
        final: ResultMessage | None = None
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                await stream.handle(message.event)
                continue
            text = assistant_text(message)
            if text is not None:
                last_text = text
                self._emit("assistant.text", {"text": text})
            if isinstance(message, ResultMessage):
                final = message
        if final is not None and final.session_id:
            self.session_id = final.session_id
        if final is not None and final.is_error:
            return self._failed_turn(TURN_FAILED, _diagnostic(final), final)
        result_text = final.result if final is not None and final.result else None
        return FrontTurn(
            text=last_text or result_text or "",
            structured=final.structured_output if final is not None else None,
            usage=usage_from_message(final),
        )

    def _failed_turn(
        self, template: str, diagnostic: str, final: ResultMessage | None
    ) -> FrontTurn:
        self._emit(TURN_ERROR, {"diagnostic": diagnostic})
        return FrontTurn(
            text=template.format(diagnostic=diagnostic),
            usage=usage_from_message(final),
            error=diagnostic,
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            self._events.emit(event_type, payload)


class _ReplyStream:
    """Feeds the partial JSON of the StructuredOutput tool to `on_speech` / `on_text`.

    Each StructuredOutput block gets its own extractor; partial input of any other tool
    (`delegate`, MCP proxies) is ignored.
    """

    def __init__(self, on_text: TextCallback | None, on_speech: TextCallback | None) -> None:
        self._callbacks = {"display_text": on_text, "speech_text": on_speech}
        self._extractors: dict[int, PartialJsonFieldExtractor] = {}

    async def handle(self, event: dict[str, Any]) -> None:
        kind, index = event.get("type"), event.get("index")
        if kind == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use" and block.get("name") == STRUCTURED_OUTPUT_TOOL:
                self._extractors[index] = PartialJsonFieldExtractor()
        elif kind == "content_block_stop":
            self._extractors.pop(index, None)
        elif kind == "content_block_delta" and index in self._extractors:
            partial = (event.get("delta") or {}).get("partial_json")
            if isinstance(partial, str):
                for field_name, text in self._extractors[index].feed(partial):
                    callback = self._callbacks[field_name]
                    if callback is not None:
                        await callback(text)


def _diagnostic(final: ResultMessage) -> str:
    detail = final.result or "; ".join(final.errors or []) or "sin detalle"
    return f"{final.subtype}: {detail}"
