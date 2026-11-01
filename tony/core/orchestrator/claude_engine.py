import warnings
from collections.abc import Callable, Collection
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
    TextBlock,
    ToolPermissionContext,
    create_sdk_mcp_server,
)

from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.ports import EngineOutcome, ProxiedTool, Usage

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


def outcome_from_messages(messages: list[Any]) -> EngineOutcome:
    last_text = ""
    final: ResultMessage | None = None
    for message in messages:
        if isinstance(message, AssistantMessage):
            texts = [block.text for block in message.content if isinstance(block, TextBlock)]
            last_text = "".join(texts) or last_text
        elif isinstance(message, ResultMessage):
            final = message
    if final is None:
        return EngineOutcome(text=last_text)
    if final.is_error:
        raise EngineError(f"{final.subtype}: {final.result}" if final.result else final.subtype)
    usage = final.usage or {}
    return EngineOutcome(
        text=final.result or last_text,
        structured=final.structured_output,
        usage=[Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0))],
    )


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
            messages = [message async for message in client.receive_response()]
        return outcome_from_messages(messages)
