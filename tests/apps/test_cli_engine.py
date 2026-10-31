"""Engine commands over an isolated agent inventory."""

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import write_agent
from tony.apps.cli.main import app
from tony.core.loader.frontmatter import split_frontmatter

runner = CliRunner()


@pytest.fixture
def inventory(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    (tmp_repo / "config/tony.yaml").write_text(
        "engines:\n  coding:\n    type: litellm\n    model: gpt-4o-mini\n"
        "  fast:\n    type: litellm\n    model: gpt-4o\n"
    )
    write_agent(tmp_repo / "agents", "viernes")
    write_agent(tmp_repo / "agents/viernes/subagents", "helper")
    return tmp_repo


@pytest.mark.parametrize(
    "name,relative",
    [
        ("viernes", "viernes"),
        ("viernes/helper", "viernes/subagents/helper"),
        ("helper", "viernes/subagents/helper"),
    ],
)
def test_set_valid_profile(inventory, name, relative):
    path = inventory / "agents" / relative / "agent.md"
    before, body = split_frontmatter(path.read_text())
    result = runner.invoke(app, ["engine", "set", name, "coding"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == f"Motor de '{name}' cambiado a 'coding'."
    assert split_frontmatter(path.read_text()) == ({**before, "engine": "coding"}, body)


def test_unknown_profile_does_not_write(inventory):
    path = inventory / "agents/viernes/agent.md"
    before = path.read_bytes()
    result = runner.invoke(app, ["engine", "set", "viernes", "missing"])
    assert result.exit_code == 2
    for name in ("missing", "claude_sdk", "coding", "fast"):
        assert name in result.output
    assert path.read_bytes() == before


def test_missing_agent(inventory):
    result = runner.invoke(app, ["engine", "set", "nadie", "coding"])
    assert result.exit_code == 2
    assert "No existe el agente 'nadie'" in result.output


def test_list_resolves_profiles_and_indents_children(inventory):
    child = inventory / "agents/viernes/subagents/helper/agent.md"
    child.write_text(child.read_text().replace("role: worker", "role: worker\nengine: fast"))
    result = runner.invoke(app, ["engine", "list", "--agents-dir", str(inventory / "agents")])
    assert result.exit_code == 0, result.output
    rows = result.stdout.splitlines()
    assert rows[0].replace("|", " ").split() == ["agente", "motor", "tipo"]
    assert any(
        line.replace("|", " ").split() == ["viernes", "claude_sdk", "claude_sdk"] for line in rows
    )
    assert any(
        line.startswith("  helper")
        and line.replace("|", " ").split() == ["helper", "fast", "litellm"]
        for line in rows
    )


@pytest.mark.parametrize(
    "args,spanish",
    [([], "Gestiona el motor"), (["set"], "Cambia el motor"), (["list"], "Lista los agentes")],
)
def test_help_in_spanish(args, spanish):
    result = runner.invoke(app, ["engine", *args, "--help"])
    assert result.exit_code == 0
    assert spanish in result.stdout


def test_ambiguous_subagent_requires_qualified_name(inventory):
    write_agent(inventory / "agents", "otro")
    write_agent(inventory / "agents/otro/subagents", "helper")
    files = list((inventory / "agents").rglob("agent.md"))
    before = {path: path.read_bytes() for path in files}
    result = runner.invoke(app, ["engine", "set", "helper", "coding"])
    assert result.exit_code == 2
    assert "ambiguo" in result.output and "agente/subagente" in result.output
    assert {path: path.read_bytes() for path in files} == before


def test_invalid_agent_header_is_not_overwritten(inventory):
    path = inventory / "agents/viernes/agent.md"
    path.write_text("No YAML")
    result = runner.invoke(app, ["engine", "set", "viernes", "coding"])
    assert result.exit_code == 2
    assert "frontmatter" in result.output
    assert path.read_text() == "No YAML"
