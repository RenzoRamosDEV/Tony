"""Tests for tool/tool.json loading (specs/agent-loader)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tony.core.config import load_settings
from tony.core.loader import (
    NATIVE_TOOLS,
    AgentLoadError,
    HttpServer,
    MissingEnvVar,
    StdioServer,
    load_agent,
    substitute_env,
)

AGENT_MD = "---\nname: a\nrole: worker\nmodel: claude-sonnet\n---\nHola\n"

REFERENCE_TOOL_JSON = {
    "mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/renzo"],
        },
        "notion": {"url": "https://mcp.notion.com/mcp"},
    },
    "native": ["run_subagent", "read_skill", "remember"],
    "allow": ["filesystem.*", "notion.search"],
    "confirm": ["filesystem.write_file", "filesystem.delete"],
}


@pytest.fixture
def settings():
    return load_settings(None)


def make_agent(tmp_repo: Path, tool_json: dict | None) -> Path:
    folder = tmp_repo / "agents" / "a"
    folder.mkdir(parents=True)
    (folder / "agent.md").write_text(AGENT_MD, encoding="utf-8")
    if tool_json is not None:
        (folder / "tool").mkdir()
        (folder / "tool" / "tool.json").write_text(json.dumps(tool_json), encoding="utf-8")
    return folder


def test_reference_example_with_stdio_and_http(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, REFERENCE_TOOL_JSON)

    tools = load_agent(folder, settings, {}).tools

    assert tools.mcpServers["filesystem"] == StdioServer(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/home/renzo"],
    )
    assert tools.mcpServers["notion"] == HttpServer(url="https://mcp.notion.com/mcp")
    assert tools.native == ["run_subagent", "read_skill", "remember"]
    assert tools.allow == ["filesystem.*", "notion.search"]
    assert tools.confirm == ["filesystem.write_file", "filesystem.delete"]


def test_server_with_command_and_url_is_rejected(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"x": {"command": "c", "url": "http://u"}}})

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert "x" in str(exc_info.value)


def test_server_without_command_or_url_is_rejected(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"x": {"args": []}}})

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert "x" in str(exc_info.value)


def test_native_tool_outside_catalog_is_rejected(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"native": ["teleport"]})

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "teleport" in message
    for name in NATIVE_TOOLS:
        assert name in message


def test_native_catalog_is_the_five_documented_tools() -> None:
    assert set(NATIVE_TOOLS) == {
        "delegate",
        "remember",
        "set_reply_mode",
        "read_skill",
        "run_subagent",
    }


def test_missing_tool_json_yields_empty_config(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, None)

    tools = load_agent(folder, settings, {}).tools

    assert tools.mcpServers == {}
    assert tools.native == []
    assert tools.allow is None
    assert tools.confirm == []


def test_absent_allow_stays_none_not_empty_list(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"fs": {"command": "x"}}})

    assert load_agent(folder, settings, {}).tools.allow is None


def test_empty_allow_stays_empty_list(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"allow": []})

    assert load_agent(folder, settings, {}).tools.allow == []


def test_env_substitution_in_args(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo, {"mcpServers": {"fs": {"command": "x", "args": ["${HOME}/notas"]}}}
    )

    tools = load_agent(folder, settings, {"HOME": "/home/renzo"}).tools

    assert tools.mcpServers["fs"].args == ["/home/renzo/notas"]


def test_env_substitution_in_headers(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo,
        {
            "mcpServers": {
                "n": {"url": "http://u", "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"}}
            }
        },
    )

    tools = load_agent(folder, settings, {"NOTION_TOKEN": "abc"}).tools

    assert tools.mcpServers["n"].headers == {"Authorization": "Bearer abc"}


def test_env_substitution_in_env_and_url(tmp_repo: Path, settings) -> None:
    folder = make_agent(
        tmp_repo,
        {
            "mcpServers": {
                "s": {"command": "x", "env": {"KEY": "${K}"}},
                "h": {"url": "${BASE}/mcp"},
            }
        },
    )

    tools = load_agent(folder, settings, {"K": "v", "BASE": "http://b"}).tools

    assert tools.mcpServers["s"].env == {"KEY": "v"}
    assert tools.mcpServers["h"].url == "http://b/mcp"


def test_missing_variable_names_variable_and_server(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"notion": {"url": "${NOTION_URL}"}}})

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    message = str(exc_info.value)
    assert "NOTION_URL" in message and "notion" in message


def test_substitute_env_replaces_every_occurrence() -> None:
    assert substitute_env("${A}-${B}-${A}", {"A": "1", "B": "2"}) == "1-2-1"


def test_substitute_env_leaves_text_without_placeholders() -> None:
    assert substitute_env("plain $A {B}", {"A": "1"}) == "plain $A {B}"


def test_substitute_env_raises_missing_env_var() -> None:
    with pytest.raises(MissingEnvVar) as exc_info:
        substitute_env("${NOPE}", {})

    assert exc_info.value.var == "NOPE"


def test_invalid_json_is_reported(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, None)
    (folder / "tool").mkdir()
    (folder / "tool" / "tool.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert "tool.json" in str(exc_info.value)


def test_tool_json_failures_carry_agent_name(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"notion": {"url": "${NOTION_URL}"}}})

    with pytest.raises(AgentLoadError) as exc_info:
        load_agent(folder, settings, {})

    assert exc_info.value.agent == "a"
    assert "Value error" not in str(exc_info.value)


def test_command_is_not_substituted(tmp_repo: Path, settings) -> None:
    folder = make_agent(tmp_repo, {"mcpServers": {"s": {"command": "${CMD}", "args": ["${A}"]}}})

    tools = load_agent(folder, settings, {"A": "x"}).tools

    assert tools.mcpServers["s"].command == "${CMD}"
    assert tools.mcpServers["s"].args == ["x"]
