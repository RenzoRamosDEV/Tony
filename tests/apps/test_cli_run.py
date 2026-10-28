"""Tests for `tony run` / `tony version` (specs/cli-run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.apps.cli_helpers import FakeManager, write_agent
from tests.fakes.fake_runner import FakeAgentRunner
from tony import __version__
from tony.apps.cli import main
from tony.apps.cli.confirm_gate import CliConfirmGate
from tony.core.mcp import ConfirmRequest, McpServerStatus
from tony.core.runner import TaskResult

runner = CliRunner()
OK_RESULT = TaskResult(status="ok", resumen="Hecho", pasos=["a", "b"])


@pytest.fixture
def cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh repo layout in cwd with viernes/jarvis agents and injected fakes."""
    monkeypatch.chdir(tmp_repo)
    write_agent(tmp_repo / "agents", "viernes", "worker")
    write_agent(tmp_repo / "agents", "jarvis", "front")
    state = {"runner": FakeAgentRunner(OK_RESULT), "manager": FakeManager(), "factory_args": []}

    def runner_factory(settings, task_id, gate, call):
        state["factory_args"].append((settings, task_id, gate, call))
        return state["runner"]

    monkeypatch.setattr(main, "runner_factory", runner_factory)
    monkeypatch.setattr(main, "manager_factory", lambda settings: state["manager"])
    return state


def invoke(*args: str):
    return runner.invoke(main.app, list(args))


def test_ok_result_prints_summary_steps_and_footer(cli) -> None:
    result = invoke("run", "viernes", "lista los .md")

    assert result.exit_code == 0
    assert "Hecho" in result.output
    assert "1. a" in result.output
    assert "2. b" in result.output
    assert "Errores" not in result.output
    footer = result.output.strip().splitlines()[-1]
    assert footer.startswith("tokens: 10/5 · coste: $0.0100 · log: ")
    log_path = Path(footer.split("log: ", 1)[1])
    assert log_path.exists()
    event_types = [json.loads(line)["type"] for line in log_path.read_text().splitlines()]
    assert event_types[:2] == ["mcp.status", "task.started"]
    assert event_types[-1] == "task.finished"
    assert cli["manager"].stopped is True


def test_errors_are_printed(cli) -> None:
    cli["runner"] = FakeAgentRunner(
        TaskResult(
            status="ok",
            resumen="r",
            errores=["Tool filesystem.write_file no confirmada por el usuario"],
        )
    )

    result = invoke("run", "viernes", "x")

    assert "Tool filesystem.write_file no confirmada por el usuario" in result.output


def test_json_output_is_only_the_task_result(cli) -> None:
    result = invoke("run", "viernes", "x", "--json")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "status": "ok",
        "resumen": "Hecho",
        "datos": None,
        "pasos": ["a", "b"],
        "errores": [],
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [("ok", 0), ("partial", 0), ("error", 1), ("cancelled", 1), ("timeout", 1)],
)
def test_exit_code_follows_status(cli, status: str, code: int) -> None:
    cli["runner"] = FakeAgentRunner(TaskResult(status=status, resumen="r"))

    assert invoke("run", "viernes", "x").exit_code == code


def test_unknown_agent_exits_2_and_names_it(cli) -> None:
    result = invoke("run", "nadie", "x")

    assert result.exit_code == 2
    assert "nadie" in result.output
    assert cli["factory_args"] == []


def test_front_agent_exits_2(cli) -> None:
    result = invoke("run", "jarvis", "x")

    assert result.exit_code == 2
    assert "jarvis" in result.output and "worker" in result.output
    assert cli["factory_args"] == []


def test_broken_agent_exits_2_with_load_error(cli, tmp_repo: Path) -> None:
    write_agent(tmp_repo / "agents", "roto", "helper")

    result = invoke("run", "roto", "x")

    assert result.exit_code == 2
    assert "roto" in result.output and "role" in result.output


def test_agents_dir_and_config_options_are_respected(cli, tmp_path: Path) -> None:
    other_agents = tmp_path / "otros"
    write_agent(other_agents, "lunes", "worker")
    config = tmp_path / "tony.yaml"
    config.write_text("limits:\n  tool_timeout_s: 7\n", encoding="utf-8")

    result = invoke("run", "lunes", "x", "--agents-dir", str(other_agents), "--config", str(config))

    assert result.exit_code == 0
    settings = cli["factory_args"][0][0]
    assert settings.limits.tool_timeout_s == 7
    assert cli["runner"].calls[0][0].name == "lunes"


def test_invalid_config_exits_2_with_field_path(cli, tmp_path: Path) -> None:
    config = tmp_path / "tony.yaml"
    config.write_text('limits:\n  tool_timeout_s: "veinte"\n', encoding="utf-8")

    result = invoke("run", "viernes", "x", "--config", str(config))

    assert result.exit_code == 2
    assert "limits.tool_timeout_s" in result.output


def test_runner_receives_request_built_from_task(cli) -> None:
    invoke("run", "viernes", "lista los .md")

    _, request, _ = cli["runner"].calls[0]
    assert request.model_dump() == {
        "objetivo": "lista los .md",
        "contexto": "",
        "restricciones": [],
    }


def test_run_help_describes_options_in_spanish() -> None:
    result = invoke("run", "--help")

    assert result.exit_code == 0
    for option, word in (
        ("--json", "JSON"),
        ("--agents-dir", "agentes"),
        ("--config", "configuración"),
    ):
        assert option in result.output
        assert word in result.output


def test_root_help_is_in_spanish() -> None:
    result = invoke("--help")

    assert result.exit_code == 0
    assert "run" in result.output and "version" in result.output
    assert "Ejecuta" in result.output


def test_version_prints_package_version() -> None:
    result = invoke("version")

    assert result.exit_code == 0
    assert __version__ in result.output


def test_mcp_server_errors_are_shown_and_logged(cli) -> None:
    cli["manager"].statuses = {
        "filesystem": McpServerStatus("filesystem", "error", "timeout de conexión", 0, None)
    }

    result = invoke("run", "viernes", "x")

    assert result.exit_code == 0
    assert "filesystem" in result.output and "timeout de conexión" in result.output
    footer = result.output.strip().splitlines()[-1]
    log_lines = [
        json.loads(line) for line in Path(footer.split("log: ", 1)[1]).read_text().splitlines()
    ]
    status_events = [line for line in log_lines if line["type"] == "mcp.status"]
    assert status_events[0]["payload"] == {
        "filesystem": {"state": "error", "error": "timeout de conexión", "tool_count": 0}
    }


def test_json_output_keeps_mcp_warnings_out_of_stdout(cli) -> None:
    cli["manager"].statuses = {"fs": McpServerStatus("fs", "error", "caído", 0, None)}

    result = invoke("run", "viernes", "x", "--json")

    assert json.loads(result.stdout)["status"] == "ok"


def test_run_task_wiring_uses_one_task_id_and_the_agent_tools(cli) -> None:
    result = invoke("run", "viernes", "x")

    settings, task_id, gate, call = cli["factory_args"][0]
    footer = result.output.strip().splitlines()[-1]
    assert Path(footer.split("log: ", 1)[1]).stem == task_id
    assert cli["manager"].started_with == cli["runner"].calls[0][0].tools
    assert call == cli["manager"].call
    assert isinstance(gate, CliConfirmGate)


def test_dotenv_values_are_redacted_in_the_log(cli, tmp_repo: Path) -> None:
    (tmp_repo / "config" / ".env").write_text("NOTION_TOKEN=supersecreto123\n", encoding="utf-8")
    cli["runner"] = FakeAgentRunner(
        OK_RESULT, events=[("tool.call", {"tool": "t", "args": {"q": "supersecreto123"}})]
    )

    result = invoke("run", "viernes", "x")

    raw = Path(result.output.strip().splitlines()[-1].split("log: ", 1)[1]).read_text()
    assert "supersecreto123" not in raw
    assert '"q": "***"' in raw


def test_env_values_substituted_into_tool_config_are_redacted(
    cli, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_repo / "config" / ".env").write_text("NOTION_TOKEN=oldsecret123\n", encoding="utf-8")
    monkeypatch.setenv("NOTION_TOKEN", "newsecret456")
    tool_dir = tmp_repo / "agents" / "viernes" / "tool"
    tool_dir.mkdir()
    (tool_dir / "tool.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "notion": {
                        "url": "https://mcp.notion.com/mcp",
                        "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    cli["runner"] = FakeAgentRunner(
        OK_RESULT, events=[("assistant.text", {"text": "uso newsecret456 y oldsecret123"})]
    )

    result = invoke("run", "viernes", "x")

    raw = Path(result.output.strip().splitlines()[-1].split("log: ", 1)[1]).read_text()
    assert "newsecret456" not in raw
    assert "oldsecret123" not in raw
    assert '"text": "uso *** y ***"' in raw


class ConfirmingRunner(FakeAgentRunner):
    """Asks the gate once, then behaves like FakeAgentRunner."""

    def __init__(self, gate, result: TaskResult) -> None:
        super().__init__(result)
        self.gate = gate
        self.answers: list[bool] = []

    async def run(self, spec, request, tools, events):
        request_ = ConfirmRequest.create("t", "fs.write_file", {"path": "a.md"})
        self.answers.append(await self.gate.confirm(request_))
        return await super().run(spec, request, tools, events)


def test_confirmation_under_json_keeps_stdout_parseable(cli) -> None:
    def runner_factory(settings, task_id, gate, call):
        cli["runner"] = ConfirmingRunner(gate, OK_RESULT)
        return cli["runner"]

    main.runner_factory = runner_factory

    result = runner.invoke(main.app, ["run", "viernes", "x", "--json"], input="s\n")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ok"
    assert "¿Confirmas? [s/N]" in result.stderr
    assert cli["runner"].answers == [True]
