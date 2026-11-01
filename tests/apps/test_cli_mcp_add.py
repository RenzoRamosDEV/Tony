import json

import pytest
from typer.testing import CliRunner

from tests.core.orchestrator.skills_home import write_subagent
from tests.core.orchestrator.viernes_home import make_viernes_home
from tony.apps.cli.main import create_app

FILE = "agents/viernes/tool/tool.json"


@pytest.fixture
def home(tmp_path):
    return make_viernes_home(tmp_path)[0]


def mcp(home, *args):
    return CliRunner().invoke(create_app(), ["mcp", *args], env={"TONY_HOME": str(home)})


def servers(home, file=FILE):
    return json.loads((home / file).read_text())["mcpServers"]


def test_stdio_entry_with_args_and_env(home):
    result = mcp(
        home,
        "add", "notas", "npx",
        "--arg", "-y",
        "--arg", "@modelcontextprotocol/server-filesystem",
        "--arg", "${HOME}/notas",
        "--env", "LOG=1",
        "--agent", "viernes",
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert result.stdout == f"added notas to {FILE}\n"
    assert servers(home)["notas"] == {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/notas"],
        "env": {"LOG": "1"},
    }
    assert "filesystem" in servers(home)


def test_plain_command_has_no_empty_keys(home):
    assert mcp(home, "add", "reloj", "uvx", "--agent", "viernes").exit_code == 0

    assert servers(home)["reloj"] == {"command": "uvx"}


@pytest.mark.parametrize("url", ["https://example.test/mcp", "http://localhost:9/mcp"])
def test_http_entry_with_headers(home, url):
    result = mcp(
        home, "add", "remoto", url,
        "--header", "Authorization=Bearer ${REMOTE_TOKEN}",
        "--agent", "viernes",
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert servers(home)["remoto"] == {
        "url": url,
        "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"},
    }


@pytest.mark.parametrize(
    ("args", "option"),
    [
        (["x", "npx", "--header", "A=b"], "--header"),
        (["x", "https://e.test", "--arg", "a"], "--arg"),
        (["x", "https://e.test", "--env", "A=b"], "--env"),
        (["x", "npx", "--env", "TOKEN"], "--env"),
        (["x", "npx", "--env", "=x"], "--env"),
        (["x", "npx", "--header", "sin-igual"], "--header"),
    ],
)
def test_usage_errors_leave_file_unchanged(home, args, option):
    before = (home / FILE).read_bytes()

    result = mcp(home, "add", *args, "--agent", "viernes")

    assert result.exit_code == 2
    assert option in result.stderr
    assert (home / FILE).read_bytes() == before


def test_agent_is_required(home):
    result = mcp(home, "add", "x", "npx")

    assert result.exit_code == 2
    assert "--agent" in result.output


@pytest.mark.parametrize("name", ["filesystem", "tony", "a.b"])
def test_refused_name_names_it(home, name):
    before = (home / FILE).read_bytes()

    result = mcp(home, "add", name, "npx", "--agent", "viernes")

    assert result.exit_code != 0
    assert name in result.stderr
    assert (home / FILE).read_bytes() == before


def test_guard_agent_refused(home):
    result = mcp(home, "add", "x", "npx", "--agent", "edith")

    assert result.exit_code != 0
    assert "guard" in result.stderr
    assert not (home / "agents/edith/tool").exists()


def test_subagent_target(home):
    write_subagent(home, "resumidor")

    result = mcp(home, "add", "notas", "npx", "--agent", "viernes/resumidor")

    assert result.exit_code == 0, result.output
    sub_file = "agents/viernes/subagents/resumidor/tool/tool.json"
    assert servers(home, sub_file)["notas"] == {"command": "npx"}


def test_literal_secret_warned_and_never_echoed(home):
    result = mcp(home, "add", "gh", "npx", "--env", "GITHUB_TOKEN=s3cr3t", "--agent", "viernes")

    assert result.exit_code == 0
    assert servers(home)["gh"]["env"] == {"GITHUB_TOKEN": "s3cr3t"}
    assert "GITHUB_TOKEN" in result.stderr and "${" in result.stderr
    assert "s3cr3t" not in result.stdout and "s3cr3t" not in result.stderr


def test_placeholder_secret_not_warned(home):
    result = mcp(
        home, "add", "gh", "npx", "--env", "GITHUB_TOKEN=${GITHUB_TOKEN}", "--agent", "viernes"
    )

    assert result.exit_code == 0
    assert result.stderr == ""
