"""Options of the front's persistent session (specs/front-agent: opciones seguras, MCPs)."""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from tests.core.runner_helpers import fake_catalog
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.loader import AgentSpec, ToolConfig
from tony.core.mcp import ToolCatalog
from tony.core.runner.claude_sdk import BUILTIN_TOOLS, make_can_use_tool
from tony.core.runner.conversation import build_front_options
from tony.core.runner.native_tools import build_native_server
from tony.core.runner.proxy import TaskState, ToolProxyFactory
from tony.core.runner.reply_mode import FrontReply


class Handlers:
    async def delegate(self, request):
        raise NotImplementedError

    async def remember(self, text):
        return text

    async def set_reply_mode(self, mode):
        return mode


def front_spec(native: list[str] | None = None, max_steps: int = 12) -> AgentSpec:
    return AgentSpec(
        name="jarvis",
        role="front",
        model="claude-haiku",
        max_steps=max_steps,
        system_prompt="Eres Jarvis.",
        path=Path("/tmp/jarvis"),
        tools=ToolConfig(native=native or ["delegate", "remember", "set_reply_mode"]),
    )


async def noop_call(qualified, args, timeout):
    raise NotImplementedError


def proxies_for(catalog: ToolCatalog):
    factory = ToolProxyFactory(
        catalog, noop_call, AutoConfirmGate(True), ListEventSink(), TaskState("front"), 20, 60
    )
    return factory.build()


def test_front_options_keep_the_worker_defences_and_expose_tony() -> None:
    spec = front_spec()
    settings = load_settings(None)

    options = build_front_options(
        spec,
        settings,
        build_native_server(spec.tools.native, Handlers()),
        {},
        make_can_use_tool(ToolCatalog.empty()),
    )

    assert options.tools == []
    assert options.disallowed_tools == list(BUILTIN_TOOLS)
    assert options.permission_mode == "default"
    assert options.setting_sources == []
    assert options.allowed_tools == ["mcp__tony__*"]
    assert list(options.mcp_servers) == ["tony"]
    assert options.strict_mcp_config is True
    assert options.max_turns == 12
    assert options.model == "claude-haiku-5-5"
    assert options.output_format == {
        "type": "json_schema",
        "schema": FrontReply.model_json_schema(),
    }
    assert options.system_prompt.startswith("Eres Jarvis.")
    assert "`delegate`" in options.system_prompt
    assert options.resume is None
    assert options.include_partial_messages is True
    assert options.effort == "low"


def test_the_structured_reply_schema_lists_speech_text_first() -> None:
    assert list(FrontReply.model_json_schema()["properties"]) == ["speech_text", "display_text"]


def test_front_with_declared_mcp_sees_its_allowed_proxies_only() -> None:
    spec = front_spec()
    catalog = fake_catalog(allow=["fake.echo"])

    options = build_front_options(
        spec,
        load_settings(None),
        build_native_server(spec.tools.native, Handlers()),
        proxies_for(catalog),
        make_can_use_tool(catalog),
    )

    assert options.allowed_tools == ["mcp__tony__*", "mcp__fake__*"]
    assert list(options.mcp_servers) == ["tony", "fake"]


async def test_can_use_tool_denies_tools_outside_the_front_catalog() -> None:
    can_use_tool = make_can_use_tool(fake_catalog(allow=["fake.echo"]))

    assert isinstance(await can_use_tool("mcp__fake__destroy", {}, None), PermissionResultDeny)
    assert isinstance(await can_use_tool("mcp__fake__echo", {}, None), PermissionResultAllow)
    assert isinstance(await can_use_tool("Bash", {}, None), PermissionResultDeny)


def test_resume_is_passed_through_to_the_options() -> None:
    spec = front_spec()

    options = build_front_options(
        spec,
        load_settings(None),
        build_native_server(spec.tools.native, Handlers()),
        {},
        make_can_use_tool(ToolCatalog.empty()),
        resume="s1",
    )

    assert options.resume == "s1"
