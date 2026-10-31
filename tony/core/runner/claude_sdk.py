"""AgentRunner adapter over the Claude Agent SDK."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack
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
from tony.core.runner.auth import claude_account_options
from tony.core.runner.cancel import CancelToken
from tony.core.runner.contracts import TaskRequest, TaskResult
from tony.core.runner.native_tools import SERVER_NAME, NativeToolSet, worker_native_tools
from tony.core.runner.ports import EventSink
from tony.core.runner.prompt import build_system_prompt, build_user_prompt
from tony.core.runner.proxy import TaskState, ToolCaller, ToolProxyFactory
from tony.core.runner.results import cancelled_result, error_result, timeout_result
from tony.core.skills.triggers import matched_skills

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
SKILL_ACTIVATED = "skill.activated"

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
    native_server: McpSdkServerConfig | None = None,
) -> ClaudeAgentOptions:
    servers = dict(proxies)
    if native_server is not None:
        servers[SERVER_NAME] = native_server
    return ClaudeAgentOptions(
        **claude_account_options(settings.engines[spec.engine]),
        tools=[],
        allowed_tools=[f"{MCP_PREFIX}{server}__*" for server in servers],
        disallowed_tools=list(BUILTIN_TOOLS),
        system_prompt=build_system_prompt(spec, request, now=now),
        mcp_servers=servers,
        permission_mode="default",
        max_turns=spec.max_steps,
        model=settings.models[spec.model],
        effort=spec.effort,
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
        return error_result(_sdk_diagnostic(message), steps or [])
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
        cancel_token: CancelToken | None = None,
        native_handlers: Any = None,
    ) -> None:
        self._settings = settings
        self._task_id = task_id
        self._gate = gate
        self._call = call
        self._client_factory = client_factory
        self._cleanup_budget_s = cleanup_budget_s
        self._cancel_token = cancel_token
        self._native_handlers = native_handlers
        self._factory: ToolProxyFactory | None = None
        self.native_tools: NativeToolSet | None = None

    def proxy_handler(self, qualified: str):
        assert self._factory is not None, "run() has not built the proxies yet"
        return self._factory.handler(qualified)

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        events.emit("task.started", {"agent": spec.name, **request.model_dump()})
        limits = self._settings.limits
        state = TaskState(self._task_id, cancel_token=self._cancel_token or CancelToken())
        self._factory = ToolProxyFactory(
            tools,
            self._call,
            self._gate,
            events,
            state,
            limits.tool_timeout_s,
            limits.confirm_timeout_s,
        )
        self.native_tools = self._build_native_tools(spec, events)
        options = build_options(
            spec,
            request,
            tools,
            self._settings,
            self._factory.build(),
            make_can_use_tool(tools),
            native_server=self.native_tools.build() if self.native_tools else None,
        )
        transcript = _Transcript()
        deadline = asyncio.get_running_loop().time() + limits.task_timeout_s
        result: TaskResult | None = None
        for skill in matched_skills(f"{request.objetivo}\n{request.contexto}", spec.skills):
            events.emit(SKILL_ACTIVATED, {"skill": skill.name})
        prompt = build_user_prompt(request, spec.skills)
        try:
            async with asyncio.timeout_at(deadline + self._cleanup_budget_s):
                result = await self._drive(options, prompt, state, transcript, events, deadline)
        except TimeoutError:
            if transcript.final is None:
                result = timeout_result(limits.task_timeout_s, state.steps)
        except Exception as exc:  # noqa: BLE001 - every engine failure becomes a TaskResult
            result = error_result(str(exc) or exc.__class__.__name__, state.steps)
        if state.cancelled:
            result = cancelled_result(state)
        if result is None:
            result = result_from_message(transcript.final, transcript.last_text, list(state.steps))
        events.emit(
            "task.finished",
            {"status": result.status, "usage": usage_from_message(transcript.final)},
        )
        return result

    def _build_native_tools(self, spec: AgentSpec, events: EventSink) -> NativeToolSet | None:
        native = worker_native_tools(spec.tools.native)
        if not native or self._native_handlers is None:
            return None
        return NativeToolSet(native, self._native_handlers, events)

    async def _drive(
        self,
        options: ClaudeAgentOptions,
        prompt: str,
        state: TaskState,
        transcript: _Transcript,
        events: EventSink,
        deadline: float,
    ) -> TaskResult | None:
        """Connect, query and consume the response under the task deadline.

        The deadline covers the client's connect too; the caller bounds disconnect.
        """
        client = self._client_factory(options)
        async with AsyncExitStack() as stack:
            async with asyncio.timeout_at(deadline):
                await stack.enter_async_context(client)
            state.interrupt = client.interrupt
            try:
                async with asyncio.timeout_at(deadline):
                    await client.query(prompt)
                    await consume_until_cancelled(_consume(client, transcript, events), state)
            except TimeoutError:
                await state.request_interrupt()
                return timeout_result(self._settings.limits.task_timeout_s, state.steps)
        return None


async def _consume(client: SdkClient, transcript: _Transcript, events: EventSink) -> None:
    async for message in client.receive_response():
        transcript.consume(message, events)


async def consume_until_cancelled(consuming: Coroutine[Any, Any, None], state: TaskState) -> None:
    """Race the model's response against the task's cancel token.

    When the token fires first the engine is interrupted and the response is abandoned;
    the caller turns the cancelled state into the TaskResult.
    """
    response = asyncio.ensure_future(consuming)
    cancelled = asyncio.ensure_future(state.cancel_token.wait())
    try:
        done, _ = await asyncio.wait({response, cancelled}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        cancelled.cancel()
        response.cancel()
    if response in done:
        response.result()
        return
    await state.request_interrupt()
    await asyncio.gather(response, return_exceptions=True)


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
