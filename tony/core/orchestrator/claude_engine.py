import dataclasses
import warnings
from collections.abc import Callable, Collection, Iterable
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    CanUseTool,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    TextBlock,
    ToolPermissionContext,
    create_sdk_mcp_server,
)

from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.ports import (
    ChatOutcome,
    EngineOutcome,
    ProxiedTool,
    TextCallback,
    Usage,
)

# allowed_tools auto-approves the proxy servers before can_use_tool runs. That is intended:
# the ToolProxy is the execution barrier; can_use_tool only has to deny non-proxied names.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

MCP_PREFIX = "mcp__"
SEPARATOR = "__"
BUILTIN_TOOLS: tuple[str, ...] = (
    "Agent",
    "Bash",
    "BashOutput",
    "Edit",
    "Glob",
    "Grep",
    "KillBash",
    "LS",
    "MultiEdit",
    "NotebookEdit",
    "Read",
    "Skill",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)


def to_sdk_name(tool_id: str) -> str:
    server, _, name = tool_id.partition(".")
    return f"{MCP_PREFIX}{server}{SEPARATOR}{name}"


def from_sdk_name(sdk_name: str) -> str | None:
    if not sdk_name.startswith(MCP_PREFIX):
        return None
    server, separator, name = sdk_name.removeprefix(MCP_PREFIX).partition(SEPARATOR)
    if not (server and separator and name):
        return None
    return f"{server}.{name}"


def sdk_tool(tool: ProxiedTool) -> SdkMcpTool[Any]:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        reply = await tool.handler(args)
        return {"content": [{"type": "text", "text": reply.text}], "is_error": reply.is_error}

    return SdkMcpTool(
        name=tool.id.partition(".")[2],
        description=tool.description,
        input_schema=tool.input_schema,
        handler=handler,
    )


def build_options(
    spec: AgentSpec, tools: list[ProxiedTool], model_id: str, can_use_tool: CanUseTool
) -> ClaudeAgentOptions:
    by_server: dict[str, list[SdkMcpTool[Any]]] = {}
    for tool in tools:
        by_server.setdefault(tool.id.partition(".")[0], []).append(sdk_tool(tool))
    return ClaudeAgentOptions(
        tools=[],
        allowed_tools=[f"{MCP_PREFIX}{server}{SEPARATOR}*" for server in by_server],
        disallowed_tools=list(BUILTIN_TOOLS),
        system_prompt=spec.system_prompt,
        mcp_servers={
            server: create_sdk_mcp_server(server, tools=server_tools)
            for server, server_tools in by_server.items()
        },
        strict_mcp_config=True,
        setting_sources=[],
        model=model_id,
        can_use_tool=can_use_tool,
        output_format={"type": "json_schema", "schema": TaskResult.model_json_schema()},
    )


def build_chat_options(
    spec: AgentSpec,
    system_prompt: str,
    tools: list[ProxiedTool],
    model_id: str,
    can_use_tool: CanUseTool,
) -> ClaudeAgentOptions:
    return dataclasses.replace(
        build_options(spec, tools, model_id, can_use_tool),
        system_prompt=system_prompt,
        output_format=None,
        include_partial_messages=True,
    )


def text_delta(message: Any) -> str | None:
    if not isinstance(message, StreamEvent) or message.event.get("type") != "content_block_delta":
        return None
    delta = message.event.get("delta") or {}
    return delta.get("text") if delta.get("type") == "text_delta" else None


class EngineError(Exception):
    pass


def make_can_use_tool(catalog: Collection[str]) -> CanUseTool:
    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResult:
        if from_sdk_name(tool_name) in catalog:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"tool {tool_name} is not a proxied tool of this agent")

    return can_use_tool


class OutcomeAccumulator:
    """Folds streamed SDK messages into an outcome without retaining them."""

    def __init__(self) -> None:
        self._last_text = ""
        self._final: ResultMessage | None = None

    def add(self, message: Any) -> None:
        if isinstance(message, AssistantMessage):
            texts = [block.text for block in message.content if isinstance(block, TextBlock)]
            self._last_text = "".join(texts) or self._last_text
        elif isinstance(message, ResultMessage):
            self._final = message

    def outcome(self) -> EngineOutcome:
        final = self._final
        if final is None:
            return EngineOutcome(text=self._last_text)
        if final.is_error:
            raise EngineError(f"{final.subtype}: {final.result}" if final.result else final.subtype)
        usage = final.usage or {}
        return EngineOutcome(
            text=final.result or self._last_text,
            structured=final.structured_output,
            usage=[Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0))],
        )


def outcome_from_messages(messages: Iterable[Any]) -> EngineOutcome:
    accumulator = OutcomeAccumulator()
    for message in messages:
        accumulator.add(message)
    return accumulator.outcome()


class ClaudeEngine:
    """ModelEngine adapter over the Claude Agent SDK."""

    def __init__(
        self, client_factory: Callable[[ClaudeAgentOptions], Any] = ClaudeSDKClient
    ) -> None:
        self._client_factory = client_factory

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: list[ProxiedTool], model_id: str
    ) -> EngineOutcome:
        can_use_tool = make_can_use_tool({tool.id for tool in tools})
        options = build_options(spec, tools, model_id, can_use_tool)
        async with self._client_factory(options) as client:
            await client.query(request.model_dump_json())
            accumulator = OutcomeAccumulator()
            async for message in client.receive_response():
                accumulator.add(message)
        return accumulator.outcome()

    async def converse(
        self,
        spec: AgentSpec,
        system_prompt: str,
        prompt: str,
        tools: list[ProxiedTool],
        model_id: str,
        on_text: TextCallback,
    ) -> ChatOutcome:
        can_use_tool = make_can_use_tool({tool.id for tool in tools})
        options = build_chat_options(spec, system_prompt, tools, model_id, can_use_tool)
        accumulator = OutcomeAccumulator()
        async with self._client_factory(options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                chunk = text_delta(message)
                if chunk:
                    on_text(chunk)
                accumulator.add(message)
        outcome = accumulator.outcome()
        return ChatOutcome(text=outcome.text, usage=outcome.usage)
