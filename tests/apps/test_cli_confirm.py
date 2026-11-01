import json

from typer.testing import CliRunner

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import FakeWording
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.apps.cli.main import create_app

OK = {"resumen": "Borrada.", "datos": None, "pasos": ["borrar"], "errores": []}
RULE = "filesystem.delete*/confirm"


def invoke(home, steps, answer, wording=None):
    engines, wordings = [], []

    def engine_factory():
        engines.append(FakeModelEngine([*steps, Final(structured=OK)]))
        return engines[-1]

    def wording_factory(system_prompt, model_id):
        wordings.append((system_prompt, model_id))
        return wording or FakeWording(error=RuntimeError("offline"))

    app = create_app(
        engine_factory=engine_factory,
        wording_factory=wording_factory,
        readline_factory=lambda: lambda: answer,
    )
    result = CliRunner().invoke(app, ["run", "viernes", "Borra a.md"], env={"TONY_HOME": str(home)})
    return result, engines, wordings


def delete(notes):
    return [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"})]


def test_yes_on_the_terminal_runs_the_tool(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    result, _, wordings = invoke(home, delete(notes), "s\n")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == OK
    assert result.stdout.count("\n") == 1
    question = (
        f'Acción: filesystem.delete_file {{"path": "{notes}/a.md"}}. Regla: {RULE}. ¿Autoriza?'
    )
    assert question in result.stderr and "¿Autoriza?" not in result.stdout
    assert not (notes / "a.md").exists()
    [(prompt, model_id)] = wordings
    assert "Acción: <qué>. Regla: <rule id>. ¿Autoriza?" in prompt
    assert model_id == "claude-haiku-5-5"


def test_worded_question_shown_on_stderr(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    worded = f"Acción: borrar a.md. Regla: {RULE}. ¿Autoriza?"

    result, _, _ = invoke(home, delete(notes), "sí\n", wording=FakeWording(text=worded))

    assert result.exit_code == 0
    assert worded in result.stderr


def test_no_cancels_and_exits_one(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    result, _, _ = invoke(home, delete(notes), "no\n")

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "resumen": "",
        "datos": None,
        "pasos": [],
        "errores": [
            f"tarea cancelada: el usuario no autorizó filesystem.delete_file (regla {RULE})"
        ],
    }
    assert (notes / "a.md").exists()


def test_invalid_policy_exits_two_naming_file_and_field(tmp_path):
    home, _ = make_viernes_home(tmp_path, policy="default: confirm\nrules:\n  - {match: a}\n")

    result, engines, _ = invoke(home, [], "s\n")

    assert result.exit_code == 2
    assert "agents/edith/policy.yaml" in result.stderr and "rules.0.verdict" in result.stderr
    assert result.stdout == ""
    assert all(engine.request is None for engine in engines)
