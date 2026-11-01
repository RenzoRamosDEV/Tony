import shutil
from pathlib import Path

from typer.testing import CliRunner

from tony.apps.cli.main import create_app

REPO = Path(__file__).resolve().parents[2]


def invoke(home):
    return CliRunner().invoke(create_app(), ["agents"], env={"TONY_HOME": str(home)})


def bundled_home(tmp_path):
    shutil.copytree(REPO / "agents", tmp_path / "agents")
    return tmp_path


def test_lists_the_three_slots(tmp_path):
    result = invoke(bundled_home(tmp_path))

    assert result.exit_code == 0
    rows = [line.split() for line in result.stdout.splitlines()]
    assert rows == [
        ["slot", "agent", "role", "model", "voice"],
        ["front", "jarvis", "front", "claude-haiku", "kokoro/em_alex"],
        ["worker", "viernes", "worker", "claude-sonnet", "kokoro/em_alex"],
        ["guard", "edith", "guard", "claude-haiku", "kokoro/ef_dora"],
    ]


def test_invalid_agent_fails_naming_file_and_field(tmp_path):
    home = bundled_home(tmp_path)
    agent_md = home / "agents" / "jarvis" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: front", "role: helper"))

    result = invoke(home)

    assert result.exit_code != 0
    assert "agents/jarvis/agent.md" in result.stderr
    assert "role" in result.stderr
    assert result.stdout == ""
