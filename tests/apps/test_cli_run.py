import json

import pytest
from typer.testing import CliRunner

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import FakeModelEngine, Final
from tony.apps.cli.main import create_app

OK = {"resumen": "Tienes una nota.", "datos": ["a.md"], "pasos": ["listar"], "errores": []}


@pytest.fixture
def home(tmp_path):
    return make_viernes_home(tmp_path)[0]


def invoke(home, *args, structured=OK):
    engines = []

    def factory():
        engines.append(FakeModelEngine([Final(text="raw", structured=structured)]))
        return engines[-1]

    result = CliRunner().invoke(
        create_app(engine_factory=factory), list(args), env={"TONY_HOME": str(home)}
    )
    return result, engines


def test_successful_run_prints_single_json_object(home):
    result, [engine] = invoke(home, "run", "viernes", "Lista mis notas")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == OK
    assert result.stdout.count("\n") == 1
    assert engine.request.model_dump() == {
        "objetivo": "Lista mis notas",
        "contexto": "",
        "restricciones": [],
    }


def test_result_with_errors_exits_non_zero(home):
    failed = {**OK, "errores": ["no encontré la carpeta"]}

    result, _ = invoke(home, "run", "viernes", "x", structured=failed)

    assert result.exit_code == 1
    assert json.loads(result.stdout) == failed


def test_unknown_agent_names_folder_and_prints_no_result(home):
    result, engines = invoke(home, "run", "nadie", "x")

    assert result.exit_code == 2
    assert "agents/nadie/" in result.stderr
    assert result.stdout == ""
    assert all(engine.request is None for engine in engines)


def test_invalid_definition_prints_file_and_field(home):
    agent_md = home / "agents" / "viernes" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: worker", "role: helper"))

    result, _ = invoke(home, "run", "viernes", "x")

    assert result.exit_code == 2
    assert "agents/viernes/agent.md" in result.stderr and "role" in result.stderr
    assert result.stdout == ""


def test_non_worker_agent_exits_non_zero(home):
    agent_md = home / "agents" / "viernes" / "agent.md"
    agent_md.write_text(agent_md.read_text().replace("role: worker", "role: front"))

    result, _ = invoke(home, "run", "viernes", "hola")

    assert result.exit_code == 2
    assert "not a worker" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("task", ["", "   "])
def test_blank_task_is_rejected_before_running(home, task):
    result, engines = invoke(home, "run", "viernes", task)

    assert result.exit_code == 2
    assert "objetivo" in result.stderr
    assert engines == []


def test_help_lists_run_command(home):
    result, _ = invoke(home, "--help")

    assert result.exit_code == 0
    assert "run" in result.stdout


def test_no_arguments_shows_help(home):
    result, _ = invoke(home)

    assert "Usage" in result.output and "run" in result.output
    assert "Tony: asistente personal local." in result.output
