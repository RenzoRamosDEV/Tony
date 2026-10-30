"""`tony agents` and `tony agents show` (specs/cli-agents) with CliRunner over tmp_repo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tests.apps.cli_helpers import write_agent
from tony.apps.cli import main

runner = CliRunner()
NOTION = {
    "url": "https://mcp.notion.com/mcp",
    "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"},
}


def write_skill(agent: Path, name: str, frontmatter: str) -> None:
    path = agent / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{frontmatter}---\ncuerpo\n", encoding="utf-8")


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_repo)
    agents = tmp_repo / "agents"
    write_agent(agents, "viernes", "worker")
    (agents / "viernes" / "tool").mkdir()
    (agents / "viernes" / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": {"notion": NOTION}, "native": ["read_skill", "run_subagent"]}),
        encoding="utf-8",
    )
    write_skill(
        agents / "viernes",
        "resumen-web",
        "name: resumen-web\ndescription: Resume\ntrigger: [resume]\n",
    )
    write_agent(agents / "viernes" / "subagents", "investigador", "worker")
    write_agent(agents, "jarvis", "front", model="claude-haiku")
    (tmp_repo / "config" / ".env").write_text("NOTION_TOKEN=s3cr3t\n", encoding="utf-8")
    return agents


def invoke(*args: str):
    return runner.invoke(main.app, ["agents", *args])


def rows(output: str) -> list[str]:
    return [line for line in output.splitlines() if "|" in line]


def test_list_shows_agents_and_indented_subagents(cli) -> None:
    result = invoke()

    assert result.exit_code == 0, result.output
    viernes = next(r for r in rows(result.stdout) if r.startswith("viernes"))
    cells = [c.strip() for c in viernes.split("|")]
    assert cells == ["viernes", "worker", "claude-sonnet", "1", "1", "read_skill, run_subagent"]
    investigador = next(r for r in rows(result.stdout) if "investigador" in r)
    assert investigador.startswith("  investigador")
    assert [c.strip() for c in investigador.split("|")][1:5] == [
        "worker",
        "claude-sonnet",
        "0",
        "0",
    ]
    jarvis = next(r for r in rows(result.stdout) if r.startswith("jarvis"))
    assert [c.strip() for c in jarvis.split("|")][:3] == ["jarvis", "front", "claude-haiku"]
    for header in ("nombre", "rol", "modelo", "skills", "MCP", "nativas"):
        assert header in result.stdout


def test_broken_agent_is_marked_without_hiding_the_others(cli) -> None:
    write_agent(cli, "roto", "helper")

    result = invoke()

    assert result.exit_code == 0
    roto = next(r for r in result.stdout.splitlines() if "roto" in r)
    assert roto.startswith("✗") and "role" in roto
    assert any(r.startswith("viernes") for r in rows(result.stdout))


def test_invalid_skill_is_listed_under_its_agent(cli) -> None:
    write_skill(cli / "viernes", "mala", "name: mala\n")

    result = invoke()

    lines = result.stdout.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("viernes"))
    assert lines[index + 1].strip().startswith("✗ skill mala:")
    assert "description" in lines[index + 1]


def test_broken_subagent_is_listed_under_its_parent(cli) -> None:
    write_agent(cli / "viernes" / "subagents", "malo", "helper")

    result = invoke()

    assert any(line.strip().startswith("✗ subagente malo:") for line in result.stdout.splitlines())


def test_show_prints_the_resolved_spec_without_secrets(cli) -> None:
    result = invoke("show", "viernes")

    assert result.exit_code == 0, result.output
    data = yaml.safe_load(result.stdout)
    assert data["name"] == "viernes" and data["role"] == "worker"
    assert data["tools"]["mcpServers"]["notion"]["url"] == "https://mcp.notion.com/mcp"
    assert data["tools"]["mcpServers"]["notion"]["headers"]["Authorization"] == "***"
    assert "s3cr3t" not in result.stdout
    assert data["skills"] == [
        {"name": "resumen-web", "description": "Resume", "triggers": ["resume"]}
    ]
    assert "cuerpo" not in result.stdout
    assert list(data["subagents"]) == ["investigador"]
    assert data["subagents"]["investigador"]["parent"] == "viernes"
    assert "path" not in data and "secrets" not in data


def test_show_accepts_agent_slash_subagent(cli) -> None:
    result = invoke("show", "viernes/investigador")

    assert result.exit_code == 0, result.output
    assert yaml.safe_load(result.stdout)["name"] == "investigador"


@pytest.mark.parametrize("name", ["nadie", "viernes/nadie", "nadie/x"])
def test_show_of_an_unknown_agent_exits_2(cli, name: str) -> None:
    result = invoke("show", name)

    assert result.exit_code == 2
    assert "nadie" in result.stderr


def test_show_of_a_broken_agent_exits_2_with_the_error(cli) -> None:
    write_agent(cli, "roto", "helper")

    result = invoke("show", "roto")

    assert result.exit_code == 2 and "role" in result.stderr


def test_help_is_in_spanish() -> None:
    assert "agents" in runner.invoke(main.app, ["--help"]).stdout
    top = invoke("--help").stdout
    assert "show" in top and "--agents-dir" in top and "--config" in top
    assert "agentes" in top.lower()
    assert "YAML" in invoke("show", "--help").stdout


GOLDEN_SUBAGENT_YAML = """\
name: investigador
role: worker
model: claude-sonnet
engine: claude_sdk
persona:
  address: ''
  language: es
style:
  voice: ''
  text: ''
max_steps: 20
wait_phrase: Dame un momento.
system_prompt: Eres investigador.
tools:
  mcpServers: {}
  native: []
  allow: null
  confirm: []
skill_errors: []
subagent_errors: {}
parent: viernes
skills: []
subagents: {}
"""


def test_show_subagent_matches_the_golden_yaml(cli) -> None:
    assert invoke("show", "viernes/investigador").stdout == GOLDEN_SUBAGENT_YAML


def test_list_matches_the_golden_table(cli) -> None:
    result = invoke()

    assert result.stdout.splitlines() == [
        "nombre         | rol    | modelo        | skills | MCP | nativas                 ",
        "---------------+--------+---------------+--------+-----+-------------------------",
        "jarvis         | front  | claude-haiku  | 0      | 0   | -                       ",
        "viernes        | worker | claude-sonnet | 1      | 1   | read_skill, run_subagent",
        "  investigador | worker | claude-sonnet | 0      | 0   | -                       ",
    ]


def test_missing_agents_dir_or_invalid_config_exit_2(cli, tmp_path: Path) -> None:
    missing = invoke("--agents-dir", str(tmp_path / "nadie"))
    assert missing.exit_code == 2 and "nadie" in missing.stderr

    (cli.parent / "config" / "tony.yaml").write_text("reply_mode: loud\n", encoding="utf-8")
    invalid = invoke()
    assert invalid.exit_code == 2 and "reply_mode" in invalid.stderr


def test_show_redacts_secrets_that_only_a_subagent_uses(cli) -> None:
    fetch = {"command": "x", "env": {"PASSWORD": "${CHILD_PASSWORD}"}}
    (cli / "viernes" / "subagents" / "investigador" / "tool").mkdir()
    (cli / "viernes" / "subagents" / "investigador" / "tool" / "tool.json").write_text(
        json.dumps({"mcpServers": {"fetch": fetch}}), encoding="utf-8"
    )
    with (cli.parent / "config" / ".env").open("a", encoding="utf-8") as env:
        env.write("CHILD_PASSWORD=clave-larga-del-hijo\n")

    result = invoke("show", "viernes")

    assert result.exit_code == 0, result.output
    assert "clave-larga-del-hijo" not in result.stdout
    env = yaml.safe_load(result.stdout)["subagents"]["investigador"]["tools"]["mcpServers"]["fetch"]
    assert env["env"]["PASSWORD"] == "***"
