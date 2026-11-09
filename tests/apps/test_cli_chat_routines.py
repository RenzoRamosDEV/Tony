import json

import pytest

from tests.apps.test_cli_chat import DONE, NO_PIN_POLICY, home_with, invoke, paced
from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import FakeModelEngine, Final
from tests.fakes.routines import run_statuses, seed_due_routine


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def test_due_routine_runs_during_chat_without_printing_its_result(tmp_path):
    home = home_with(tmp_path, NO_PIN_POLICY)
    seed_due_routine(home)
    worker = FakeModelEngine([Final(structured={**DONE, "resumen": "RESULTADO-SECRETO-RUTINA"})])
    lines = paced("Hola", lambda: run_statuses(home) == ["ok"], "otra", "/salir")

    result, _ = invoke(home, lines, FakeChatEngine([Say("uno")], [Say("dos")]), worker=worker)

    assert result.exit_code == 0
    assert "Jarvis: uno" in result.stdout and "Jarvis: dos" in result.stdout
    assert "RESULTADO-SECRETO-RUTINA" not in result.stdout
    assert worker.request.objetivo == "resume mis notas"
    (log,) = (home / "logs" / "tasks").glob("*.jsonl")
    assert json.loads(log.read_text().splitlines()[0])["origin"] == "routine"


def test_routine_stays_queued_while_the_session_is_locked(tmp_path):
    home = home_with(tmp_path, SHIPPED_POLICY_YAML)
    seed_due_routine(home)
    worker = FakeModelEngine([Final(structured=DONE)])
    lines = paced("Hola", lambda: run_statuses(home) == ["queued"], "/salir")

    result, _ = invoke(home, lines, FakeChatEngine([Say("uno")]), worker=worker)

    assert result.exit_code == 0
    assert run_statuses(home) == ["queued"] and worker.request is None
