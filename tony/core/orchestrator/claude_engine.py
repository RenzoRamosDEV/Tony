from typing import Any

from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from tony.core.events.messages import TaskResult
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.ports import ProxiedTool

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
