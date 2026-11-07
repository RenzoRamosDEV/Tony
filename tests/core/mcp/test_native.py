import pytest

from tests.fakes.sinks import ListEventSink
from tests.fakes.variables import secret_variables
from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import SecretMasker
from tony.core.loader.tool_json import ToolSpec, parse_tool_spec
from tony.core.mcp.manager import McpManager
from tony.core.mcp.native import NativeScope, NativeTool
from tony.core.orchestrator.natives import NATIVE_TOOLS
from tony.core.orchestrator.ports import ToolReply


async def fixed_now(args):
    return ToolReply(text="2026-11-01T10:00:00Z")


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


def test_production_registry_keys():
    assert set(NATIVE_TOOLS) == {"read_skill", "run_subagent"}


@pytest.mark.parametrize("name", ["read_skill", "run_subagent"])
def test_production_factories_bind_a_native_tool(tmp_path, name):
    tool = NATIVE_TOOLS[name](NativeScope(root=tmp_path, agent="viernes"))

    assert isinstance(tool, NativeTool)
    assert tool.input_schema["type"] == "object"


def test_factory_receives_scope_with_agent_key(tmp_path):
    seen = []

    def factory(scope):
        seen.append(scope)
        return NOW

    scope = NativeScope(root=tmp_path, agent="viernes/resumidor")

    assert factory(scope) is NOW
    assert (seen[0].agent, seen[0].root) == ("viernes/resumidor", tmp_path)


def test_loader_still_rejects_unknown_native():
    with pytest.raises(DefinitionError) as info:
        parse_tool_spec(
            '{"mcpServers": {}, "native": ["now"]}', file="f.json", native_tools=NATIVE_TOOLS
        )
    assert info.value.field == "native"


async def test_declared_native_without_a_registry_is_skipped_not_a_keyerror(tmp_path):
    """A connectivity probe passes no native registry; declared natives must not crash
    construction, since the probe never calls them."""
    spec = ToolSpec.model_validate({"mcpServers": {}, "native": ["read_skill", "run_subagent"]})
    manager = McpManager(
        spec,
        variables=secret_variables({}),
        masker=SecretMasker(),
        sink=ListEventSink(),
        log_dir=tmp_path,
    )

    async with manager:
        assert manager.tools == []


async def test_manager_defaults_to_no_natives(tmp_path):
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
