"""`tony mcp add|remove|list` (specs/cli-mcp) with CliRunner, FakeManager and the fake MCP."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import FakeManager, write_agent
from tony.apps.cli import main
from tony.apps.cli.mcp_cli import AddRequest, parse_add_tokens
from tony.core.mcp import McpServerStatus

runner = CliRunner()
FAKE_CMD = ["--", sys.executable, "-m", "tests.fakes.fake_mcp_server"]


def test_parse_stdio_tokens_with_options_after_the_double_dash() -> None:
    request = parse_add_tokens(
        ["npx", "-y", "@modelcontextprotocol/server-fetch", "--agent", "viernes"]
    )

    assert request == AddRequest(
        url=None, command="npx", args=["-y", "@modelcontextprotocol/server-fetch"], agent="viernes"
    )


def test_parse_url_with_headers_allow_confirm_and_env() -> None:
    request = parse_add_tokens(
        [
            "https://mcp.notion.com/mcp",
            "--agent",
            "viernes",
            "--header",
            "Authorization=Bearer ${NOTION_TOKEN}",
            "--allow",
            "notion.search",
            "--confirm",
            "notion.delete",
            "--env",
            "TOKEN=${TOKEN}",
            "--force",
        ]
    )

    assert request.url == "https://mcp.notion.com/mcp" and request.command is None
    assert request.headers == {"Authorization": "Bearer ${NOTION_TOKEN}"}
    assert request.allow == ["notion.search"] and request.confirm == ["notion.delete"]
    assert request.env == {"TOKEN": "${TOKEN}"} and request.force is True


def test_parse_keeps_unknown_options_as_server_args() -> None:
    request = parse_add_tokens(["cmd", "--port", "8", "--agent", "v", "--verbose"])

    assert request.command == "cmd" and request.args == ["--port", "8", "--verbose"]
    assert request.agent == "v"


def test_parse_rejects_a_malformed_key_value() -> None:
    with pytest.raises(ValueError, match="K=V"):
        parse_add_tokens(["cmd", "--header", "sin-igual"])


def test_parse_of_an_empty_command_has_no_target() -> None:
    assert parse_add_tokens(["--agent", "v"]).command is None


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_repo)
    write_agent(tmp_repo / "agents", "viernes", "worker")
    write_agent(tmp_repo / "agents", "jarvis", "front", model="claude-haiku")
    state = {"managers": []}

    class ReadyManager(FakeManager):
        def status(self) -> dict[str, McpServerStatus]:
            servers = self.started_with.mcpServers if self.started_with else {}
            return {name: McpServerStatus(name, "ready", None, 4, None) for name in servers}

    def manager_factory(settings):
        manager = ReadyManager()
        state["managers"].append(manager)
        return manager

    state["manager_factory"] = manager_factory
    return state


def invoke(*args: str):
    return runner.invoke(main.app, ["mcp", *args])


def tool_json(agent: str = "viernes") -> dict:
    return json.loads(Path(f"agents/{agent}/tool/tool.json").read_text(encoding="utf-8"))


def write_tool_json(data: dict, agent: str = "viernes") -> None:
    tool = Path(f"agents/{agent}/tool")
    tool.mkdir(exist_ok=True)
    (tool / "tool.json").write_text(json.dumps(data), encoding="utf-8")


def test_add_stdio_server_connects_and_reports_tools(cli) -> None:
    write_tool_json(
        {"mcpServers": {"filesystem": {"command": "x"}}, "confirm": ["filesystem.write_file"]}
    )

    result = invoke("add", "fake", *FAKE_CMD, "--agent", "viernes")

    assert result.exit_code == 0, result.output
    assert "fake: 4 tools (allow: todas)" in result.stdout
    data = tool_json()
    assert data["mcpServers"]["fake"] == {
        "command": sys.executable,
        "args": ["-m", "tests.fakes.fake_mcp_server"],
    }
    assert "filesystem" in data["mcpServers"] and data["confirm"] == ["filesystem.write_file"]


def test_add_http_server_with_headers_allow_and_env(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    monkeypatch.setenv("NOTION_TOKEN", "secreto-de-prueba")

    result = invoke(
        "add",
        "notion",
        "https://mcp.notion.com/mcp",
        "--agent",
        "viernes",
        "--header",
        "Authorization=Bearer ${NOTION_TOKEN}",
        "--allow",
        "notion.search",
    )

    assert result.exit_code == 0, result.output
    assert tool_json()["mcpServers"]["notion"] == {
        "url": "https://mcp.notion.com/mcp",
        "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"},
    }
    assert tool_json()["allow"] == ["notion.search"]
    assert "notion" in result.stdout and "notion.search" in result.stdout


def test_add_passes_env_to_the_server(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])

    result = invoke("add", "x", "--", "cmd", "--agent", "viernes", "--env", "TOKEN=${TOKEN}")

    assert result.exit_code == 0, result.output
    assert tool_json()["mcpServers"]["x"] == {"command": "cmd", "env": {"TOKEN": "${TOKEN}"}}


def test_add_to_an_unknown_agent_exits_2(cli) -> None:
    result = invoke("add", "x", "--", "cmd", "--agent", "nadie")

    assert result.exit_code == 2
    assert "nadie" in result.stderr


def test_add_without_agent_or_target_exits_2(cli) -> None:
    assert invoke("add", "x", "--", "cmd").exit_code == 2
    assert invoke("add", "x", "--agent", "viernes").exit_code == 2


def test_add_creates_a_missing_tool_json(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])

    result = invoke("add", "fetch", "--", "npx", "-y", "pkg", "--agent", "viernes")

    assert result.exit_code == 0, result.output
    assert tool_json() == {"mcpServers": {"fetch": {"command": "npx", "args": ["-y", "pkg"]}}}


def test_add_of_an_existing_name_fails_unless_forced(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_tool_json({"mcpServers": {"fetch": {"command": "a"}}})

    result = invoke("add", "fetch", "--", "otro", "--agent", "viernes")
    assert result.exit_code == 1
    assert "fetch" in result.stderr and "--force" in result.stderr
    assert tool_json()["mcpServers"]["fetch"] == {"command": "a"}

    forced = invoke("add", "fetch", "--", "b", "--agent", "viernes", "--force")
    assert forced.exit_code == 0, forced.output
    assert tool_json()["mcpServers"]["fetch"]["command"] == "b"


def test_add_with_a_failing_connection_keeps_the_entry_and_warns(cli) -> None:
    result = invoke("add", "roto", "--", "/no/existe", "--agent", "viernes")

    assert result.exit_code == 0, result.output
    assert tool_json()["mcpServers"]["roto"] == {"command": "/no/existe"}
    assert "roto" in result.stderr and "Aviso" in result.stderr


def test_remove_deletes_the_server_and_keeps_the_rest(cli) -> None:
    write_tool_json(
        {
            "mcpServers": {"filesystem": {"command": "x"}, "fetch": {"command": "y"}},
            "native": ["read_skill"],
            "allow": ["filesystem.*"],
            "confirm": ["filesystem.write_file"],
        }
    )

    result = invoke("remove", "fetch", "--agent", "viernes")

    assert result.exit_code == 0, result.output
    data = tool_json()
    assert list(data["mcpServers"]) == ["filesystem"]
    assert data["native"] == ["read_skill"]
    assert data["allow"] == ["filesystem.*"] and data["confirm"] == ["filesystem.write_file"]


def test_remove_of_an_unknown_server_exits_1(cli) -> None:
    write_tool_json({"mcpServers": {}})

    result = invoke("remove", "nadie", "--agent", "viernes")

    assert result.exit_code == 1
    assert "nadie" in result.stderr


def test_list_connects_and_shows_state_tools_allow_and_confirm(cli) -> None:
    write_tool_json(
        {
            "mcpServers": {
                "fake": {"command": sys.executable, "args": ["-m", "tests.fakes.fake_mcp_server"]}
            },
            "confirm": ["fake.destroy"],
        }
    )

    result = invoke("list", "--agent", "viernes")

    assert result.exit_code == 0, result.output
    row = next(line for line in result.stdout.splitlines() if "fake" in line and "viernes" in line)
    for cell in ("viernes", "fake", "stdio", "ready", "4", "todas", "fake.destroy"):
        assert cell in row
    for header in ("agente", "servidor", "transporte", "estado", "tools", "allow", "confirm"):
        assert header in result.stdout


def test_list_without_connect_reads_config_only(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_tool_json({"mcpServers": {"fake": {"command": "x"}, "n": {"url": "https://n"}}})
    write_tool_json({"mcpServers": {"j": {"command": "y"}}}, agent="jarvis")

    result = invoke("list", "--no-connect")

    assert result.exit_code == 0, result.output
    assert cli["managers"] == []
    rows = [line for line in result.stdout.splitlines() if "|" in line]
    assert any("viernes" in r and "fake" in r and "stdio" in r and " - " in r for r in rows)
    assert any("viernes" in r and "n" in r and "http" in r for r in rows)
    assert any("jarvis" in r and "j" in r for r in rows)


def test_list_shows_subagent_servers_as_agent_slash_subagent(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_agent(Path("agents/viernes/subagents"), "investigador", "worker")
    write_tool_json(
        {"mcpServers": {"fetch": {"command": "f"}}}, agent="viernes/subagents/investigador"
    )

    result = invoke("list", "--no-connect")

    assert any(
        "viernes/investigador" in line and "fetch" in line for line in result.stdout.splitlines()
    )


def test_list_with_a_broken_server_shows_error_and_exits_0(cli) -> None:
    write_tool_json({"mcpServers": {"roto": {"command": "/no/existe"}}})

    result = invoke("list", "--agent", "viernes")

    assert result.exit_code == 0, result.output
    assert any("roto" in line and "error" in line for line in result.stdout.splitlines())


def test_list_of_an_unknown_agent_exits_2(cli) -> None:
    assert invoke("list", "--agent", "nadie").exit_code == 2


def test_help_is_in_spanish() -> None:
    top = runner.invoke(main.app, ["--help"]).stdout
    assert "mcp" in top

    add = invoke("add", "--help").stdout
    for option in ("--agent", "--allow", "--confirm", "--header", "--env", "--force"):
        assert option in add
    assert "servidor" in add.lower()
    assert "Elimina" in invoke("remove", "--help").stdout
    assert "--no-connect" in invoke("list", "--help").stdout
    assert "servidores MCP" in invoke("--help").stdout


# --- connection report and listing details -------------------------------------------------------


def test_add_connects_only_the_new_server_and_reports_allow_patterns(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_tool_json({"mcpServers": {"fs": {"command": "x"}}, "allow": ["fs.*"]})

    result = invoke(
        "add",
        "n",
        "http://n.local/mcp",
        "--agent",
        "viernes",
        "--allow",
        "n.search",
        "--confirm",
        "n.delete",
    )

    assert result.exit_code == 0, result.output
    manager = cli["managers"][-1]
    assert manager.server_filter == ["n"] and manager.stopped is True
    assert "n: 4 tools (allow: n.search)" in result.stdout
    assert tool_json()["mcpServers"]["n"] == {"url": "http://n.local/mcp"}
    assert tool_json()["confirm"] == ["n.delete"]
    assert "Aviso" not in result.stdout and "Aviso" not in result.stderr


def test_add_warns_on_stderr_when_the_server_is_not_reported(cli, monkeypatch) -> None:
    def silent_factory(settings):
        manager = FakeManager()
        cli["managers"].append(manager)
        return manager

    monkeypatch.setattr(main, "manager_factory", silent_factory)

    result = invoke("add", "x", "--", "cmd", "--agent", "viernes")

    assert result.exit_code == 0
    assert "Aviso: no se pudo conectar con 'x': servidor no declarado" in result.stderr
    assert "Aviso" not in result.stdout


def test_add_warns_when_the_agent_no_longer_loads(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    monkeypatch.delenv("SIN_DEFINIR", raising=False)

    result = invoke("add", "x", "--", "cmd", "--agent", "viernes", "--env", "T=${SIN_DEFINIR}")

    assert result.exit_code == 0
    assert "Aviso: no se pudo conectar con 'x'" in result.stderr and "SIN_DEFINIR" in result.stderr
    assert cli["managers"] == []


def test_force_and_options_before_the_double_dash_are_honoured(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_tool_json({"mcpServers": {"fetch": {"command": "a"}}})

    result = invoke(
        "add",
        "fetch",
        "--agent",
        "viernes",
        "--force",
        "--confirm",
        "fetch.fetch",
        "--",
        "b",
        "--port",
        "1",
    )

    assert result.exit_code == 0, result.output
    assert tool_json()["mcpServers"]["fetch"] == {"command": "b", "args": ["--port", "1"]}
    assert tool_json()["confirm"] == ["fetch.fetch"]


def test_list_marks_a_broken_agent_and_patterns_without_allow(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_agent(Path("agents"), "roto", "helper")
    write_tool_json({"mcpServers": {"fake": {"command": "x"}}, "allow": ["otro.*"]})

    result = invoke("list", "--no-connect")

    rows = [line for line in result.stdout.splitlines() if "|" in line]
    assert any(r.startswith("roto") and "✗" in r and "role" in r for r in rows)
    fake = next(r for r in rows if r.startswith("viernes") and " fake " in r)
    assert "ninguna" in fake


def test_list_connect_reports_allow_patterns_of_the_server(cli, monkeypatch) -> None:
    monkeypatch.setattr(main, "manager_factory", cli["manager_factory"])
    write_tool_json({"mcpServers": {"fake": {"command": "x"}}, "allow": ["fake.echo", "*.x"]})

    result = invoke("list", "--agent", "viernes")

    fake = next(line for line in result.stdout.splitlines() if line.startswith("viernes"))
    assert "fake.echo, *.x" in fake and " ready " in fake and " 4 " in fake
    assert cli["managers"][-1].stopped is True


def test_invalid_config_exits_2_for_list_and_add(cli, monkeypatch) -> None:
    Path("config/tony.yaml").write_text("reply_mode: loud\n", encoding="utf-8")

    assert invoke("list", "--no-connect").exit_code == 2
    assert "reply_mode" in invoke("list", "--no-connect").stderr
    assert invoke("add", "x", "--", "cmd", "--agent", "viernes").exit_code == 2
