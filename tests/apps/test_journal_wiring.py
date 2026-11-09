import pytest
from typer.testing import CliRunner

from tests.apps.test_cli_chat import NO_PIN_POLICY, paced
from tests.core.orchestrator.tony_home import make_tony_home
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.changes import FakeChanges
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.journal import seed_stale_rows, states_on_disk
from tony.apps.cli.main import create_app
from tony.core.guard.confirm import ConsoleLines

OK = {"resumen": "Hecho.", "datos": None, "pasos": [], "errores": []}


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def run_command(home, steps, answer="s\n"):
    engine = FakeModelEngine([*steps, Final(structured=OK)])
    app = create_app(engine_factory=lambda: engine, readline_factory=lambda: lambda: answer)
    return CliRunner().invoke(app, ["run", "viernes", "Borra a.md"], env={"TONY_HOME": str(home)})


def test_run_recovers_interrupted_rows_once_and_replays_nothing(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    ids = seed_stale_rows(home)

    result = run_command(home, [])

    assert result.exit_code == 0
    assert states_on_disk(home) == {
        ids["dispatched"]: "outcome_unknown",
        ids["prepared"]: "prepared",
        ids["succeeded"]: "succeeded",
    }


def test_run_journals_the_executed_call(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    run_command(home, [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"})])

    assert list(states_on_disk(home).values()) == ["succeeded"]


def test_run_does_not_journal_a_refused_call(tmp_path):
    home, notes = make_viernes_home(tmp_path)

    run_command(home, [CallTool("filesystem.delete_file", {"path": f"{notes}/a.md"})], "n\n")

    assert states_on_disk(home) == {}


def test_chat_recovers_interrupted_rows(tmp_path):
    home = make_tony_home(tmp_path, policy=NO_PIN_POLICY)[0]
    ids = seed_stale_rows(home)
    app = create_app(
        engine_factory=lambda: FakeModelEngine([Final(structured=OK)]),
        wording_factory=None,
        chat_engine_factory=lambda: FakeChatEngine([Say("Hola")]),
        console_factory=lambda: ConsoleLines(paced("Hola")),
        getpass=lambda prompt: "",
        change_stream_factory=FakeChanges(),
    )

    result = CliRunner().invoke(app, ["chat"], env={"TONY_HOME": str(home)})

    assert result.exit_code == 0
    assert states_on_disk(home)[ids["dispatched"]] == "outcome_unknown"
    assert states_on_disk(home)[ids["prepared"]] == "prepared"


def test_run_keeps_the_pre_image_of_an_overwritten_file(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    target = f"{notes}/a.md"

    result = run_command(
        home, [CallTool("filesystem.write_file", {"path": target, "content": "nuevo"})]
    )

    assert result.exit_code == 0
    (call_id,) = states_on_disk(home)
    assert (home / "memory" / "undo" / call_id).read_text() == "# Nota A\nComprar pan."
