import json

import pytest

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import FakeConfirmer
from tests.fakes.fake_engine import FakeModelEngine
from tests.fakes.guards import RecordingGuard
from tests.fakes.journal import FakeRecorder
from tests.fakes.snapshots import FakeSnapshots
from tony.core.events.messages import Ruling
from tony.core.orchestrator.runner import (
    NotWorkerError,
    RunDeps,
    ToolUnavailableError,
    run_guarded_call,
)

TASK_ID = "d" * 32
DENY = Ruling(verdict="deny", rule="filesystem.write_file/deny")


def deps_for(home, **overrides):
    return RunDeps(
        root=home,
        engine=FakeModelEngine([]),
        environ={},
        task_id_factory=lambda: TASK_ID,
        **overrides,
    )


def task_log(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_runs_the_tool_through_the_guard_with_a_task_log_and_journal(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    recorder, confirmer = FakeRecorder(), FakeConfirmer([True])
    args = {"path": f"{notes}/a.md", "content": "revertido"}

    reply = await run_guarded_call(
        "viernes",
        "filesystem.write_file",
        args,
        deps_for(home, journal=recorder, confirmer=confirmer),
        objetivo="undo call-x",
    )

    assert not reply.is_error
    assert (notes / "a.md").read_text() == "revertido"
    assert len(confirmer.requests) == 1
    assert recorder.rows["call-1"]["tool"] == "filesystem.write_file"
    assert recorder.states() == ["prepared", "dispatched", "succeeded"]
    events = task_log(home)
    assert events[0]["type"] == "task_started"
    assert events[0]["task"]["objetivo"] == "undo call-x"
    assert [e["type"] for e in events if e["type"].startswith("tool_")] == [
        "tool_call",
        "tool_result",
    ]
    assert events[-1]["type"] == "task_finished" and events[-1]["outcome"] == "ok"


async def test_guard_denial_blocks_the_write(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    args = {"path": f"{notes}/a.md", "content": "x"}

    reply = await run_guarded_call(
        "viernes",
        "filesystem.write_file",
        args,
        deps_for(home, guard=RecordingGuard(DENY)),
        objetivo="undo",
    )

    assert reply.is_error
    assert (notes / "a.md").read_text() == "# Nota A\nComprar pan."
    assert task_log(home)[-1]["outcome"] == "error"


async def test_declined_confirmation_writes_nothing(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    args = {"path": f"{notes}/a.md", "content": "x"}

    reply = await run_guarded_call(
        "viernes",
        "filesystem.write_file",
        args,
        deps_for(home, confirmer=FakeConfirmer([False])),
        objetivo="undo",
    )

    assert reply.is_error
    assert (notes / "a.md").read_text() == "# Nota A\nComprar pan."


async def test_the_call_gets_its_own_pre_image(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    snapshots = FakeSnapshots()
    args = {"path": f"{notes}/a.md", "content": "x"}

    await run_guarded_call(
        "viernes",
        "filesystem.write_file",
        args,
        deps_for(
            home, confirmer=FakeConfirmer([True]), journal=FakeRecorder(), snapshots=snapshots
        ),
        objetivo="undo",
    )

    assert [(tool, a) for _, tool, a in snapshots.kept] == [("filesystem.write_file", args)]


async def test_tool_the_agent_lacks_is_unavailable(tmp_path):
    home, _ = make_viernes_home(tmp_path)

    with pytest.raises(ToolUnavailableError):
        await run_guarded_call("viernes", "nope.tool", {}, deps_for(home), objetivo="undo")


async def test_non_worker_agent_is_refused(tmp_path):
    from tests.core.orchestrator.tony_home import make_tony_home

    home, _ = make_tony_home(tmp_path)

    with pytest.raises(NotWorkerError):
        await run_guarded_call("jarvis", "filesystem.write_file", {}, deps_for(home), objetivo="u")
