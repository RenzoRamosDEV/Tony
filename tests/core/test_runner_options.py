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


def options_for(catalog=None, request=None, native_server=None, spec=None):
    return build_options(
        spec or worker_spec(),
        request or TaskRequest(objetivo="o"),
        catalog or fake_catalog(),
        SETTINGS,
        proxies={"fake": {"type": "sdk", "name": "fake", "instance": object()}},
        can_use_tool=noop_can_use_tool,
        now=NOW,
        native_server=native_server,
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
    assert options.include_partial_messages is False
    assert options.can_use_tool is noop_can_use_tool


def test_sdk_ignores_mcp_servers_from_any_other_configuration() -> None:
    assert options_for().strict_mcp_config is True


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


# --- skills index, trigger blocks and the native `tony` server ------------------------------

from pathlib import Path  # noqa: E402

from tony.core.loader import AgentSpec, ToolConfig  # noqa: E402
from tony.core.skills import SkillSpec  # noqa: E402

RESUMEN = SkillSpec(
    name="resumen-web",
    description="Resume una página web",
    triggers=["resume esta web"],
    body="1. Descarga la página con fetch.fetch.",
    path=Path("/s/resumen-web"),
)


def skilled_spec(native: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        system_prompt="Eres Viernes.",
        path=Path("/tmp/viernes"),
        skills=[RESUMEN],
        tools=ToolConfig(native=native or []),
    )


def test_native_server_is_added_to_mcp_servers_and_allowed_tools() -> None:
    tony = {"type": "sdk", "name": "tony", "instance": object()}

    options = options_for(native_server=tony)

    assert options.allowed_tools == ["mcp__fake__*", "mcp__tony__*"]
    assert set(options.mcp_servers) == {"fake", "tony"}
    assert options.mcp_servers["tony"] is tony


def test_without_native_server_there_is_no_tony_server() -> None:
    options = options_for()

    assert "tony" not in options.mcp_servers
    assert options.allowed_tools == ["mcp__fake__*"]


def test_system_prompt_lists_skills_without_their_bodies() -> None:
    prompt = build_system_prompt(skilled_spec(), TaskRequest(objetivo="o"), now=NOW)

    assert "Skills disponibles:" in prompt
    assert "- resumen-web: Resume una página web" in prompt
    assert "Descarga la página" not in prompt
    assert options_for(spec=skilled_spec()).system_prompt == prompt


def test_system_prompt_without_skills_has_no_index() -> None:
    assert "Skills disponibles" not in build_system_prompt(worker_spec(), TaskRequest(objetivo="o"))


def test_user_prompt_prepends_triggered_skill_blocks() -> None:
    request = TaskRequest(objetivo="Resume esta web: https://x.y")

    prompt = build_user_prompt(request, [RESUMEN])

    assert prompt.startswith(
        '<skill name="resumen-web">\n1. Descarga la página con fetch.fetch.\n</skill>'
    )
    assert prompt.endswith(request.model_dump_json())
    assert "Resuelve la siguiente tarea" in prompt


def test_user_prompt_matches_triggers_in_the_context_too() -> None:
    request = TaskRequest(objetivo="haz esto", contexto="RESUME ESTA WEB")

    assert '<skill name="resumen-web">' in build_user_prompt(request, [RESUMEN])


def test_user_prompt_without_trigger_has_no_skill_block() -> None:
    prompt = build_user_prompt(TaskRequest(objetivo="lista los ficheros"), [RESUMEN])

    assert "<skill" not in prompt
    assert prompt == build_user_prompt(TaskRequest(objetivo="lista los ficheros"))
