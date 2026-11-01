
import pytest
from typer.testing import CliRunner

from tests.core.orchestrator.skills_home import write_subagent
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.processes import processes_mentioning
from tests.fakes.servers import fake_fs_entry
from tony.apps.cli.main import create_app

BROKEN = {"command": "/nonexistent/tony-no-such-cmd"}
HEADER = ["agent", "server", "state", "tools"]
FAKE_TOOLS = "6"


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def mcp_list(home, *args):
    return CliRunner().invoke(create_app(), ["mcp", "list", *args], env={"TONY_HOME": str(home)})


def rows(output):
    return [line.split(None, 3) for line in output.splitlines()]


def test_one_up_one_down(tmp_path):
    home, notes = make_tony_home(tmp_path, extra_servers={"roto": BROKEN})

    result = mcp_list(home, "--agent", "viernes")

    assert result.exit_code == 0, result.output
    header, filesystem, broken = rows(result.stdout)
    assert header == HEADER
    assert filesystem == ["viernes", "filesystem", "ok", FAKE_TOOLS]
    assert broken[:3] == ["viernes", "roto", "error:"]
    assert broken[3].endswith(" 0") and "tony-no-such-cmd" in broken[3]
    assert processes_mentioning(str(notes)) == []


def test_agent_without_servers_prints_header_only(tmp_path):
    home, _ = make_tony_home(tmp_path)

    result = mcp_list(home, "--agent", "jarvis")

    assert result.exit_code == 0
    assert rows(result.stdout) == [HEADER]


def test_unknown_agent_names_folder(tmp_path):
    home, _ = make_tony_home(tmp_path)

    result = mcp_list(home, "--agent", "nadie")

    assert result.exit_code != 0
    assert "agents/nadie/" in result.stderr


def test_all_agents_and_subagents_in_path_order(tmp_path):
    home, notes = make_tony_home(tmp_path)
    write_subagent(home, "resumidor", servers={"notas": fake_fs_entry(str(notes))})

    result = mcp_list(home)

    assert result.exit_code == 0, result.output
    assert [row[:3] for row in rows(result.stdout)[1:]] == [
        ["viernes", "filesystem", "ok"],
        ["viernes/resumidor", "notas", "ok"],
    ]


def test_invalid_tool_json_reported_and_others_listed(tmp_path):
    home, _ = make_tony_home(tmp_path)
    (home / "agents/jarvis/tool/tool.json").write_text("roto")

    result = mcp_list(home)

    assert result.exit_code != 0
    assert "agents/jarvis/tool/tool.json" in result.stderr
    assert [row[:3] for row in rows(result.stdout)[1:]] == [["viernes", "filesystem", "ok"]]


def test_secret_in_failure_reason_is_masked(tmp_path):
    home, _ = make_tony_home(
        tmp_path, extra_servers={"roto": {"command": "/nonexistent/${API_KEY}"}}
    )
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / ".env").write_text("API_KEY=abc123\n")

    result = mcp_list(home, "--agent", "viernes")

    assert result.exit_code == 0
    assert "abc123" not in result.output
    assert "error:" in result.stdout


def test_mcp_help_lists_commands(tmp_path):
    result = CliRunner().invoke(create_app(), ["mcp", "--help"])

    assert result.exit_code == 0
    assert "add" in result.stdout and "list" in result.stdout
