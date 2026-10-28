"""AgentRunner adapter over the Claude Agent SDK."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    McpSdkServerConfig,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
)
from pydantic import ValidationError

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ToolCatalog
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.ports import EventSink
from tony.core.runner.prompt import build_system_prompt, build_user_prompt
from tony.core.runner.proxy import NOT_CONFIRMED, TaskState, ToolCaller, ToolProxyFactory

BUILTIN_TOOLS: tuple[str, ...] = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "LS",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "BashOutput",
    "KillBash",
    "Skill",
)
MCP_PREFIX = "mcp__"
CLEANUP_BUDGET_S = 5.0

# allowed_tools auto-approves the proxies before can_use_tool is consulted; that is intended:
# the proxy itself is the execution barrier and can_use_tool only guards non-proxy names.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)
UNSTRUCTURED = "respuesta no estructurada"

CanUseTool = Callable[[str, dict[str, Any], ToolPermissionContext], Any]


class SdkClient(Protocol):
    async def __aenter__(self) -> Any: ...
    async def __aexit__(self, *exc_info: Any) -> Any: ...
    async def query(self, prompt: str, session_id: str = "default") -> None: ...
    def receive_response(self) -> Any: ...
    async def interrupt(self) -> None: ...


def build_options(
    spec: AgentSpec,
    request: TaskRequest,
    catalog: ToolCatalog,
    settings: TonySettings,
    proxies: dict[str, McpSdkServerConfig],
    can_use_tool: CanUseTool,
    now: Any = None,
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        tools=[],
        allowed_tools=[f"{MCP_PREFIX}{server}__*" for server in proxies],
        disallowed_tools=list(BUILTIN_TOOLS),
        system_prompt=build_system_prompt(spec, request, now=now),
        mcp_servers=dict(proxies),
        permission_mode="default",
        max_turns=spec.max_steps,
        model=settings.models[spec.model],
        can_use_tool=can_use_tool,
        setting_sources=[],
        strict_mcp_config=True,
        output_format={"type": "json_schema", "schema": TaskResult.model_json_schema()},
        include_partial_messages=False,
    )


def make_can_use_tool(catalog: ToolCatalog) -> CanUseTool:
    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ):
        qualified = qualified_from_sdk_name(tool_name)
        if qualified is None:
            return PermissionResultDeny(message=f"tool {tool_name} no permitida: solo tools MCP")
        if qualified not in catalog:
            return PermissionResultDeny(message=f"tool {qualified} no permitida por el catálogo")
        return PermissionResultAllow()

    return can_use_tool


def qualified_from_sdk_name(tool_name: str) -> str | None:
    """`mcp__<server>__<tool>` -> `server.tool`; None for anything else."""
    if not tool_name.startswith(MCP_PREFIX):
        return None
    server, separator, name = tool_name.removeprefix(MCP_PREFIX).partition("__")
    if not separator or not server or not name:
        return None
    return f"{server}.{name}"


def result_from_message(
    message: ResultMessage | None, fallback_text: str, steps: list[str] | None = None
) -> TaskResult:
    if message is not None and message.is_error:
        return _engine_error_result(_sdk_diagnostic(message), steps or [])
    if message is not None and message.structured_output is not None:
        try:
            return TaskResult.model_validate(message.structured_output)
        except ValidationError:
            pass
    resumen = (message.result if message is not None and message.result else None) or fallback_text
    return TaskResult(status="partial", resumen=resumen, errores=[UNSTRUCTURED])


def _sdk_diagnostic(message: ResultMessage) -> str:
    return f"{message.subtype}: {message.result}" if message.result else message.subtype


def usage_from_message(message: ResultMessage | None) -> dict[str, Any]:
    usage = (message.usage if message is not None else None) or {}
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_cost_usd": (message.total_cost_usd if message is not None else None) or 0.0,
        "num_turns": message.num_turns if message is not None else 0,
    }


def assistant_text(message: Any) -> str | None:
    if not isinstance(message, AssistantMessage):
        return None
    texts = [block.text for block in message.content if isinstance(block, TextBlock)]
    return "".join(texts) if texts else None


class ClaudeSdkRunner:
    def __init__(
        self,
        settings: TonySettings,
        task_id: str,
        gate: ConfirmGate,
        call: ToolCaller,
        client_factory: Callable[[ClaudeAgentOptions], SdkClient] = ClaudeSDKClient,
        cleanup_budget_s: float = CLEANUP_BUDGET_S,
    ) -> None:
        self._settings = settings
        self._task_id = task_id
        self._gate = gate
        self._call = call
        self._client_factory = client_factory
        self._cleanup_budget_s = cleanup_budget_s
        self._factory: ToolProxyFactory | None = None

    def proxy_handler(self, qualified: str):
        assert self._factory is not None, "run() has not built the proxies yet"
        return self._factory.handler(qualified)

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        limits = self._settings.limits
        state = TaskState(self._task_id)
        self._factory = ToolProxyFactory(
            tools,
            self._call,
            self._gate,
            events,
            state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        )
        options = build_options(
            spec, request, tools, self._settings, self._factory.build(), make_can_use_tool(tools)
        )
        transcript = _Transcript()
        deadline = asyncio.get_running_loop().time() + limits.task_timeout_s
        result: TaskResult | None = None
        try:
            async with asyncio.timeout_at(deadline + self._cleanup_budget_s):
                result = await self._drive(options, request, state, transcript, events, deadline)
        except TimeoutError:
            if transcript.final is None:
                result = _timeout_result(limits.task_timeout_s, state)
        except Exception as exc:  # noqa: BLE001 - every engine failure becomes a TaskResult
            result = _error_result(exc, state)
        if state.cancelled:
            result = _cancelled_result(state)
        if result is None:
            result = result_from_message(transcript.final, transcript.last_text, list(state.steps))
        events.emit(
            "task.finished",
            {"status": result.status, "usage": usage_from_message(transcript.final)},
        )
        return result

    async def _drive(
        self,
        options: ClaudeAgentOptions,
        request: TaskRequest,
        state: TaskState,
        transcript: _Transcript,
        events: EventSink,
        deadline: float,
    ) -> TaskResult | None:
        """Connect, query and consume the response under the task deadline.

        The deadline covers the client's connect too; the caller bounds disconnect.
        """
        client = self._client_factory(options)
        async with client:
            state.interrupt = client.interrupt
            try:
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError
                async with asyncio.timeout_at(deadline):
                    await client.query(build_user_prompt(request))
                    async for message in client.receive_response():
                        transcript.consume(message, events)
            except TimeoutError:
                await state.request_interrupt()
                return _timeout_result(self._settings.limits.task_timeout_s, state)
        return None


class _Transcript:
    """What the run has seen so far: final ResultMessage and the latest assistant text."""

    def __init__(self) -> None:
        self.final: ResultMessage | None = None
        self.last_text = ""

    def consume(self, message: Any, events: EventSink) -> None:
        text = assistant_text(message)
        if text is not None:
            self.last_text = text
            events.emit("assistant.text", {"text": text})
        if isinstance(message, ResultMessage):
            self.final = message


def _timeout_result(timeout_s: float, state: TaskState) -> TaskResult:
    return TaskResult(
        status="timeout",
        resumen=f"Tarea interrumpida: superó el límite de {timeout_s:g} s.",
        pasos=list(state.steps),
        errores=[f"timeout de tarea tras {timeout_s:g} s"],
    )


def _error_result(exc: Exception, state: TaskState) -> TaskResult:
    return _engine_error_result(str(exc) or exc.__class__.__name__, list(state.steps))


def _engine_error_result(message: str, steps: list[str]) -> TaskResult:
    return TaskResult(
        status="error",
        resumen=f"Error del motor de ejecución: {message}",
        pasos=steps,
        errores=[message],
    )


def _cancelled_result(state: TaskState) -> TaskResult:
    tool_name = state.cancel_reason or "desconocida"
    return TaskResult(
        status="cancelled",
        resumen=f"Tarea cancelada: el usuario no confirmó {tool_name}.",
        datos=None,
        pasos=list(state.steps),
        errores=[NOT_CONFIRMED.format(tool=tool_name)],
    )
