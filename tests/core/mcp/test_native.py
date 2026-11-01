from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NATIVE_TOOLS, NativeTool
from tony.core.orchestrator.ports import ToolReply


async def fixed_now(args):
    return "2026-11-01T10:00:00Z"


NOW = NativeTool(description="Current time.", input_schema={"type": "object"}, run=fixed_now)


def manager_for(tmp_path, native_names, registry):
    spec = ToolSpec.model_validate({"mcpServers": {}, "native": native_names})
    return McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
        native=registry,
    )


async def test_declared_native_tool_is_exposed_as_tony_dot_name(tmp_path):
    async with manager_for(tmp_path, ["now"], {"now": NOW}) as manager:
        [tool] = manager.tools
        reply = await manager.call("tony.now", {})

    assert (tool.id, tool.server, tool.name) == ("tony.now", "tony", "now")
    assert (tool.description, tool.input_schema) == ("Current time.", {"type": "object"})
    assert reply == ToolReply(text="2026-11-01T10:00:00Z")


async def test_undeclared_native_tool_is_not_exposed(tmp_path):
    async with manager_for(tmp_path, [], {"now": NOW}) as manager:
        reply = await manager.call("tony.now", {})

    assert manager.tools == []
    assert reply.is_error is True


def test_production_registry_is_empty():
    assert NATIVE_TOOLS == {}


async def test_manager_defaults_to_production_registry(tmp_path):
    spec = ToolSpec.model_validate({"mcpServers": {}})
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
    )

    async with manager:
        assert manager.tools == []
