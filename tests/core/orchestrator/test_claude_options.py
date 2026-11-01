import pytest
from tony.core.orchestrator.claude_engine import (
    BUILTIN_TOOLS,
    build_options,
    from_sdk_name,
    sdk_tool,
    to_sdk_name,
)

from tony.core.events.messages import TaskResult
from tony.core.loader.agent_md import AgentSpec
from tony.core.orchestrator.ports import ProxiedTool, ToolReply

SPEC = AgentSpec(
    name="viernes",
    role="worker",
    model="claude-sonnet",
    persona={"language": "es", "tone": "t"},
    voice={"tts": "kokoro/em_alex"},
    system_prompt="Eres Viernes.",
)


OK = ToolReply(text="ok")


def proxied(tool_id, reply=OK):
    async def handler(args):
        return reply

    return ProxiedTool(
        id=tool_id, description=f"desc {tool_id}", input_schema={"type": "object"}, handler=handler
    )


async def allow_all(name, args, context):
    return None


TOOLS = [proxied("filesystem.read_file"), proxied("filesystem.list_directory"), proxied("tony.now")]


@pytest.fixture
def options():
    return build_options(SPEC, TOOLS, "claude-sonnet-5-5", allow_all)


class TestNameMapping:
    @pytest.mark.parametrize(
        ("tool_id", "sdk_name"),
        [
            ("filesystem.read_file", "mcp__filesystem__read_file"),
            ("tony.now", "mcp__tony__now"),
            ("remote.get.item", "mcp__remote__get.item"),
        ],
    )
    def test_round_trip(self, tool_id, sdk_name):
        assert to_sdk_name(tool_id) == sdk_name
        assert from_sdk_name(sdk_name) == tool_id

    @pytest.mark.parametrize(
        "name", ["Bash", "mcp__", "mcp__fs", "mcp__fs__", "mcp____tool", "mcp_fs__x", ""]
    )
    def test_malformed_names_map_to_none(self, name):
        assert from_sdk_name(name) is None


class TestBuildOptions:
    def test_disables_every_builtin_tool(self, options):
        assert options.tools == []
        assert set(options.disallowed_tools) == set(BUILTIN_TOOLS)
        assert {"Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch", "Task"} <= set(
            BUILTIN_TOOLS
        )

    def test_allows_only_the_agent_proxy_servers(self, options):
        assert options.allowed_tools == ["mcp__filesystem__*", "mcp__tony__*"]
        assert set(options.mcp_servers) == {"filesystem", "tony"}
        assert all(server["type"] == "sdk" for server in options.mcp_servers.values())
        assert options.strict_mcp_config is True

    def test_uses_resolved_model_and_agent_prompt(self, options):
        assert options.model == "claude-sonnet-5-5"
        assert options.system_prompt == "Eres Viernes."

    def test_ignores_filesystem_settings(self, options):
        assert options.setting_sources == []

    def test_requests_task_result_structured_output(self, options):
        assert options.output_format == {
            "type": "json_schema",
            "schema": TaskResult.model_json_schema(),
        }

    def test_passes_permission_callback(self, options):
        assert options.can_use_tool is allow_all

    def test_no_tools_means_no_servers(self):
        options = build_options(SPEC, [], "m", allow_all)

        assert (options.allowed_tools, options.mcp_servers) == ([], {})


class TestSdkTool:
    async def test_wraps_proxied_tool_under_its_short_name(self):
        tool = sdk_tool(proxied("filesystem.read_file", ToolReply(text="hola")))

        assert (tool.name, tool.description, tool.input_schema) == (
            "read_file",
            "desc filesystem.read_file",
            {"type": "object"},
        )
        assert await tool.handler({"path": "a.md"}) == {
            "content": [{"type": "text", "text": "hola"}],
            "is_error": False,
        }

    async def test_error_reply_is_flagged(self):
        tool = sdk_tool(proxied("fs.x", ToolReply(text="boom", is_error=True)))

        assert (await tool.handler({}))["is_error"] is True

    async def test_handler_forwards_args(self):
        seen = []

        async def handler(args):
            seen.append(args)
            return ToolReply(text="")

        tool = sdk_tool(ProxiedTool("fs.x", "d", {}, handler))
        await tool.handler({"a": 1})

        assert seen == [{"a": 1}]
