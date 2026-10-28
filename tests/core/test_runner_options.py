"""Tests for build_options / can_use_tool / prompts (specs/agent-runner)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from tests.core.runner_helpers import fake_catalog, worker_spec
from tony.core.config import load_settings
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.claude_sdk import BUILTIN_TOOLS, build_options, make_can_use_tool
from tony.core.runner.prompt import build_system_prompt, build_user_prompt

SETTINGS = load_settings(None)
NOW = datetime(2026, 10, 28, 10, 0, 1, tzinfo=timezone(timedelta(hours=1)))


async def noop_can_use_tool(tool_name, tool_input, context):
    return PermissionResultAllow()


def options_for(catalog=None, request=None):
    return build_options(
        worker_spec(),
        request or TaskRequest(objetivo="o"),
        catalog or fake_catalog(),
        SETTINGS,
        proxies={"fake": {"type": "sdk", "name": "fake", "instance": object()}},
        can_use_tool=noop_can_use_tool,
        now=NOW,
    )


def test_builtin_tools_are_disabled_and_only_mcp_proxies_allowed() -> None:
    options = options_for()

    assert options.tools == []
    assert set(BUILTIN_TOOLS) <= set(options.disallowed_tools)
    for name in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task"):
        assert name in options.disallowed_tools
    assert options.allowed_tools == ["mcp__fake__*"]
    assert options.permission_mode == "default"
    assert options.setting_sources == []
    assert options.mcp_servers == {
        "fake": {"type": "sdk", "name": "fake", "instance": ANY_INSTANCE}
    }


class _AnyInstance:
    def __eq__(self, other: object) -> bool:
        return True


ANY_INSTANCE = _AnyInstance()


def test_turns_model_output_format_and_streaming() -> None:
    options = options_for()

    assert options.max_turns == 20
    assert options.model == "claude-sonnet-5-5"
    assert options.output_format == {
        "type": "json_schema",
        "schema": TaskResult.model_json_schema(),
    }
    assert options.include_partial_messages is True
    assert options.can_use_tool is noop_can_use_tool


def test_system_prompt_has_context_block() -> None:
    request = TaskRequest(objetivo="o", restricciones=["no escribas ficheros"])

    prompt = build_system_prompt(worker_spec(), request, now=NOW)

    assert prompt.startswith("Eres Viernes.")
    assert "2026-10-28T10:00:01+01:00" in prompt
    assert "worker" in prompt
    assert "- no escribas ficheros" in prompt
    assert options_for(request=request).system_prompt == prompt


def test_system_prompt_without_restrictions_says_none() -> None:
    prompt = build_system_prompt(worker_spec(), TaskRequest(objetivo="o"), now=NOW)

    assert "ninguna" in prompt


def test_user_prompt_is_instruction_plus_request_json() -> None:
    request = TaskRequest(objetivo="lista", contexto="c", restricciones=["r"])

    prompt = build_user_prompt(request)

    assert prompt.startswith(
        "Resuelve la siguiente tarea y devuelve exclusivamente un TaskResult JSON.\n"
    )
    assert prompt.endswith('{"objetivo":"lista","contexto":"c","restricciones":["r"]}')


async def test_can_use_tool_denies_builtin_tool() -> None:
    decide = make_can_use_tool(fake_catalog())

    result = await decide("Bash", {"command": "ls"}, ToolPermissionContext())

    assert isinstance(result, PermissionResultDeny)
    assert "Bash" in result.message


async def test_can_use_tool_denies_mcp_tool_outside_catalog() -> None:
    decide = make_can_use_tool(fake_catalog(allow=["fake.echo"]))

    result = await decide("mcp__fake__destroy", {}, ToolPermissionContext())

    assert isinstance(result, PermissionResultDeny)
    assert "fake.destroy" in result.message


async def test_can_use_tool_allows_catalog_tool() -> None:
    decide = make_can_use_tool(fake_catalog(allow=["fake.echo"]))

    result = await decide("mcp__fake__echo", {"text": "x"}, ToolPermissionContext())

    assert isinstance(result, PermissionResultAllow)


async def test_can_use_tool_denies_malformed_mcp_name() -> None:
    decide = make_can_use_tool(fake_catalog())

    assert isinstance(await decide("mcp__fake", {}, ToolPermissionContext()), PermissionResultDeny)
