import sqlite3

import pytest

from tests.core.orchestrator.test_runtime import DONE, Harness, home_for
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.journal import seed_stale_rows, states_on_disk


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


async def test_start_recovers_interrupted_rows_and_close_releases_the_journal(tmp_path):
    home, _ = home_for(tmp_path)
    ids = seed_stale_rows(home)

    async with Harness(home) as harness:
        journal = harness.runtime.journal
        assert journal.get(ids["dispatched"]).state == "outcome_unknown"
        assert journal.get(ids["prepared"]).state == "prepared"

    with pytest.raises(sqlite3.ProgrammingError):
        journal.get(ids["prepared"])


async def test_calls_run_through_the_runtime_are_journaled(tmp_path):
    home, _ = home_for(tmp_path)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("Hecho")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Borra a.md")
        [request] = await harness.wait_for("needs_confirmation")
        harness.send(type="confirm", task_id=request["task_id"], decision="allow")
        await harness.wait_for("result", 2)

    assert "succeeded" in states_on_disk(home).values()
