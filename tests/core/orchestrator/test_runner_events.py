"""Core events published by run_task for the desktop app and the front agent."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.confirm import HANG, FakeConfirmer
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final, Hang
from tests.fakes.processes import processes_mentioning
from tony.core.events.messages import TaskRequest
from tony.core.orchestrator.ports import Usage
from tony.core.orchestrator.runner import RunDeps, run_task

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "events_delegate.jsonl"
TASK_ID = "e" * 32
REQUEST = TaskRequest(objetivo="Lee la nota a.md")
OK = {"resumen": "leída", "datos": None, "pasos": [], "errores": []}
FIXED = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


class Counter:
    """Monotonic clock advancing one second per reading."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def deps_for(home, engine, published, **extra):
    return RunDeps(
        root=home,
        engine=engine,
        environ={},
        task_id_factory=lambda: TASK_ID,
        clock=lambda: FIXED,
        monotonic=Counter(),
        publish=published.append,
        **extra,
    )


def without_ts(events):
    return [{key: value for key, value in event.items() if key != "ts"} for event in events]


def log_events(home):
    path = home / "logs" / "tasks" / f"{TASK_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def read_one(home, published):
    engine = FakeModelEngine(
        [
            CallTool("filesystem.read_file", {"path": "a.md"}),
            Final(structured=OK, usage=Usage(7, 3)),
        ]
    )
    return await run_task("viernes", REQUEST, deps_for(home, engine, published))


async def test_events_published_in_order_for_a_one_read_task(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    published = []

    await read_one(home, published)

    assert [event["type"] for event in published] == [
        "task_started",
        "mcp_status",
        "tool_call",
        "result",
    ]
    started, status, call, result = published
    assert (started["task_id"], started["agent"], started["objetivo"]) == (
        TASK_ID,
        "viernes",
        REQUEST.objetivo,
    )
    assert (status["server"], status["up"]) == ("filesystem", True)
    assert (call["verdict"], call["rule"]) == ("allow", "filesystem.read_*/allow")
    assert result["scope"] == "task" and result["outcome"] == "ok"
    assert (result["input_tokens"], result["output_tokens"]) == (7, 3)
    assert result["elapsed_ms"] == 3000
    assert result["result"] == OK


async def test_events_match_golden_file(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    published = []

    await read_one(home, published)

    expected = [json.loads(line) for line in GOLDEN.read_text().splitlines()]
    assert without_ts(published) == without_ts(expected)
    assert {event["ts"] for event in published} == {FIXED.isoformat()}


async def test_token_alert_published_with_task_id_and_logged_once(tmp_path):
    policy = SHIPPED_POLICY_YAML.replace("token_alert: 50000", "token_alert: 5")
    home, _ = make_viernes_home(tmp_path, policy=policy)
    published = []
    engine = FakeModelEngine([Final(structured=OK, usage=Usage(7, 3))])

    await run_task("viernes", REQUEST, deps_for(home, engine, published))

    [alert] = [event for event in published if event["type"] == "token_alert"]
    assert (alert["task_id"], alert["total_tokens"], alert["limit"]) == (TASK_ID, 10, 5)
    assert [event["type"] for event in log_events(home)].count("token_alert") == 1


async def test_user_cancel_stops_a_hanging_task(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    published, user_cancel = [], asyncio.Event()
    engine = FakeModelEngine([CallTool("filesystem.list_directory", {"path": "."}), Hang()])
    deps = deps_for(home, engine, published, user_cancel=user_cancel)

    task = asyncio.create_task(run_task("viernes", REQUEST, deps))
    while not engine.replies:
        await asyncio.sleep(0.01)
    user_cancel.set()
    result = await asyncio.wait_for(task, 5)

    assert result.errores == ["tarea cancelada por el usuario"]
    assert log_events(home)[-1]["outcome"] == "cancelled"
    assert published[-1]["outcome"] == "cancelled"
    assert processes_mentioning(str(notes)) == []


async def test_user_cancel_during_a_confirmation_does_not_run_the_tool(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    published, user_cancel = [], asyncio.Event()
    confirmer = FakeConfirmer([HANG])
    engine = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=OK)]
    )
    deps = deps_for(home, engine, published, user_cancel=user_cancel, confirmer=confirmer)

    task = asyncio.create_task(run_task("viernes", REQUEST, deps))
    while not confirmer.questions:
        await asyncio.sleep(0.01)
    user_cancel.set()
    result = await asyncio.wait_for(task, 5)

    assert (notes / "a.md").exists()
    assert result.errores == ["tarea cancelada por el usuario"]


async def test_publishing_masks_env_file_secrets(tmp_path):
    home, _ = make_viernes_home(tmp_path)
    (home / "config").mkdir()
    (home / "config" / ".env").write_text("SECRET_WORD=s3cr3t\n")
    published = []
    engine = FakeModelEngine([Final(structured={**OK, "resumen": "dice s3cr3t"})])

    await run_task("viernes", REQUEST, deps_for(home, engine, published))

    assert "s3cr3t" not in json.dumps(published)


async def test_external_cancellation_closes_servers_and_records_a_user_cancel(tmp_path):
    home, notes = make_viernes_home(tmp_path)
    published = []
    engine = FakeModelEngine([CallTool("filesystem.list_directory", {"path": "."}), Hang()])

    task = asyncio.create_task(run_task("viernes", REQUEST, deps_for(home, engine, published)))
    while not engine.replies:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert processes_mentioning(str(notes)) == []
    assert log_events(home)[-1]["outcome"] == "cancelled"
    assert published[-1]["outcome"] == "cancelled"
    assert published[-1]["result"]["errores"] == ["tarea cancelada por el usuario"]
