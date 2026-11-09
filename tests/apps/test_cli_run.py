import json

import pytest
from typer.testing import CliRunner

from tests.core.orchestrator.skills_home import set_native
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
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


def test_help_flag_shows_help(home):
    result, _ = invoke(home, "--help")

    assert "Usage" in result.output and "run" in result.output
    assert "Tony: asistente personal local." in result.output


NOTE_SOURCE = {
    "connector": "filesystem",
    "id": "a.md",
    "title": "Nota A",
    "retrieved_at": "2026-11-01T09:00:00Z",
    "excerpt": "Comprar pan.",
}
READ = CallTool("filesystem.read_file", {"path": "a.md"})
ASK = CallTool("tony.ask_user", {"question": "¿Qué cuenta?", "options": ["Personal", "Trabajo"]})


def run_with(home, steps, line=None):
    engine = FakeModelEngine(steps)
    app = create_app(engine_factory=lambda: engine, readline_factory=lambda: lambda: line)
    result = CliRunner().invoke(app, ["run", "viernes", "x"], env={"TONY_HOME": str(home)})
    return result, engine


def test_sources_go_to_stderr_and_stdout_stays_one_json_object(home):
    cited = {**OK, "datos": {"fuentes": [NOTE_SOURCE]}}

    result, _ = run_with(home, [READ, Final(structured=cited)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == cited
    assert result.stdout.count("\n") == 1
    assert "Fuentes:\n- filesystem · Nota A\n" in result.stderr


def test_run_without_sources_prints_nothing_extra(home):
    result, _ = run_with(home, [READ, Final(structured=OK)])

    assert "Fuentes:" not in result.stderr
    assert result.stdout.count("\n") == 1


def test_question_is_answered_from_stdin(home):
    set_native(home, "viernes", ["ask_user"])

    result, engine = run_with(home, [ASK, Final(structured=OK)], line="2\n")

    assert result.exit_code == 0
    assert engine.replies[0].text == "Trabajo"
    assert "Viernes: ¿Qué cuenta?\n1) Personal\n2) Trabajo\n" in result.stderr
    assert json.loads(result.stdout) == OK
    assert result.stdout.count("\n") == 1


def test_question_without_input_gets_no_answer(home):
    set_native(home, "viernes", ["ask_user"])

    result, engine = run_with(home, [ASK, Final(structured=OK)], line=None)

    assert (engine.replies[0].text, engine.replies[0].is_error) == ("no answer from the user", True)
    assert result.exit_code == 0
