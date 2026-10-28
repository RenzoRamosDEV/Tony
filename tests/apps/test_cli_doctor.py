"""`tony doctor` and `tony config validate` (specs/cli-doctor) over a temporary repo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import write_agent
from tony.apps.cli import doctor_cli, main
from tony.core.doctor.checks import Environment

runner = CliRunner()
FAKE = {"command": sys.executable, "args": ["-m", "tests.fakes.fake_mcp_server"]}


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_repo)
    (tmp_repo / "config" / "tony.yaml").write_text("worker: viernes\n", encoding="utf-8")
    env = tmp_repo / "config" / ".env"
    env.write_text("", encoding="utf-8")
    env.chmod(0o600)
    write_agent(tmp_repo / "agents", "viernes", "worker")
    write_agent(tmp_repo / "agents", "jarvis", "front", model="claude-haiku")
    write_tool_json({"mcpServers": {"fake": FAKE}, "confirm": ["fake.destroy"]})
    monkeypatch.setattr(
        doctor_cli,
        "environment",
        Environment(which=lambda name: f"/usr/bin/{name}", find_spec=lambda name: None),
    )
    return tmp_repo


def write_tool_json(data: dict) -> None:
    tool = Path("agents/viernes/tool")
    tool.mkdir(exist_ok=True)
    (tool / "tool.json").write_text(json.dumps(data), encoding="utf-8")


def lines(output: str, marker: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(marker)]


def test_healthy_installation_passes_offline(cli) -> None:
    result = runner.invoke(main.app, ["doctor", "--offline"])

    assert result.exit_code == 0, result.output
    assert lines(result.stdout, "✗") == []
    assert any("modelo" in line and "offline" in line for line in lines(result.stdout, "·"))
    assert any("viernes/fake" in line and "4 tools" in line for line in lines(result.stdout, "✓"))
    assert "fake.destroy" not in result.stdout


def test_induced_failures_are_reported_with_hints_and_exit_1(cli) -> None:
    (cli / "config" / ".env").chmod(0o644)
    write_agent(cli / "agents", "roto", "helper")
    write_tool_json(
        {"mcpServers": {"fake": FAKE, "broken": {"command": "/no/existe"}}, "allow": ["fake.nada"]}
    )

    result = runner.invoke(main.app, ["doctor", "--offline"])

    assert result.exit_code == 1
    failures = lines(result.stdout, "✗")
    assert any(".env" in line for line in failures)
    assert "chmod 600 config/.env" in result.stdout
    assert any("roto" in line and "role" in line for line in failures)
    assert any("broken" in line for line in failures)
    assert any("fake.nada" in line for line in failures)
    assert len(failures) == 4


def test_doctor_without_offline_probes_the_model(cli, monkeypatch) -> None:
    async def probe(settings) -> str:
        return "OK"

    monkeypatch.setattr(
        doctor_cli,
        "environment",
        Environment(which=lambda n: "/x", find_spec=lambda n: None, probe_model=probe),
    )

    result = runner.invoke(main.app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert any("modelo" in line and "OK" in line for line in lines(result.stdout, "✓"))


def test_config_validate_does_not_start_processes(cli) -> None:
    write_tool_json({"mcpServers": {"roto": {"command": "/no/existe"}}})

    result = runner.invoke(main.app, ["config", "validate"])

    assert result.exit_code == 0, result.output
    assert "mcp " not in result.stdout
    assert lines(result.stdout, "✗") == []


def test_config_validate_reports_invalid_settings(cli) -> None:
    (cli / "config" / "tony.yaml").write_text("reply_mode: loud\n", encoding="utf-8")

    result = runner.invoke(main.app, ["config", "validate"])

    assert result.exit_code == 1
    failure = next(line for line in lines(result.stdout, "✗") if "reply_mode" in line)
    for value in ("auto", "voice", "text", "both"):
        assert value in failure


def test_help_is_in_spanish() -> None:
    top = runner.invoke(main.app, ["--help"]).stdout
    assert "doctor" in top and "config" in top
    doctor = runner.invoke(main.app, ["doctor", "--help"]).stdout
    assert "--offline" in doctor and "--agents-dir" in doctor and "--config" in doctor
    assert "modelo" in doctor
    validate = runner.invoke(main.app, ["config", "validate", "--help"]).stdout
    assert "sin" in validate and "--agents-dir" in validate
