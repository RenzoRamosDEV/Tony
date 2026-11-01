import asyncio
import json
import shutil
from pathlib import Path

import pytest

from tests.core.orchestrator.viernes_home import make_viernes_home
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tony.core.events.messages import TaskRequest
from tony.core.guard.broker import ConfirmationBroker
from tony.core.guard.confirm import ConfirmationRequest
from tony.core.orchestrator.runner import RunDeps, run_task

REPO = Path(__file__).resolve().parents[3]
DELETE = "filesystem.delete_file"


def request(task_id="t1", tool=DELETE, allow_always=True):
    return ConfirmationRequest(
        task_id=task_id,
        tool=tool,
        args_preview='{"path": "a.md"}',
        question="Acción: borrar a.md. ¿Autoriza?",
        allow_always=allow_always,
    )


@pytest.fixture
def root(tmp_path):
    shutil.copytree(REPO / "agents" / "edith", tmp_path / "agents" / "edith")
    return tmp_path


def policy_bytes(root):
    return (root / "agents" / "edith" / "policy.yaml").read_bytes()


def make(root):
    published = []
    return ConfirmationBroker(root, "edith", published.append), published


async def pending(published, count=1):
    while len([e for e in published if e["type"] == "needs_confirmation"]) < count:
        await asyncio.sleep(0)


async def ask_and_answer(broker, published, decision, req=None):
    asking = asyncio.create_task(broker.ask(req or request()))
    await pending(published)
    broker.answer("t1", decision)
    return await asyncio.wait_for(asking, 1)


async def test_needs_confirmation_published_with_the_request_fields(root):
    broker, published = make(root)

    await ask_and_answer(broker, published, "deny")

    [event] = published
    assert {key: value for key, value in event.items() if key != "ts"} == {
        "type": "needs_confirmation",
        **request().model_dump(),
    }


@pytest.mark.parametrize(
    ("decision", "answer"), [("allow", True), ("always", True), ("deny", False)]
)
async def test_decisions(root, decision, answer):
    broker, published = make(root)

    assert await ask_and_answer(broker, published, decision) is answer


async def test_stale_task_id_is_ignored(root):
    broker, published = make(root)
    asking = asyncio.create_task(broker.ask(request()))
    await pending(published)

    broker.answer("t9", "allow")
    await asyncio.sleep(0.01)

    assert not asking.done()
    broker.answer("t1", "deny")
    assert await asking is False


async def test_answer_without_a_pending_request_is_ignored(root):
    broker, _ = make(root)

    broker.answer("t1", "allow")


async def test_concurrent_asks_are_published_one_after_the_other(root):
    broker, published = make(root)
    first = asyncio.create_task(broker.ask(request("t1")))
    second = asyncio.create_task(broker.ask(request("t2")))
    await pending(published)
    await asyncio.sleep(0.01)

    assert [event["task_id"] for event in published] == ["t1"]
    broker.answer("t2", "allow")
    broker.answer("t1", "allow")
    await pending(published, 2)
    assert [event["task_id"] for event in published] == ["t1", "t2"]
    broker.answer("t2", "deny")
    assert (await first, await second) == (True, False)


async def test_always_writes_the_rule_once_and_later_asks_skip_the_user(root):
    broker, published = make(root)

    await ask_and_answer(broker, published, "always")
    after_rule = policy_bytes(root)

    assert b"user-always/filesystem.delete_file" in after_rule
    assert await broker.ask(request("t2")) is True
    assert len(published) == 1
    assert policy_bytes(root) == after_rule


async def test_always_on_an_ineligible_request_allows_once_without_writing(root):
    broker, published = make(root)
    before = policy_bytes(root)
    ineligible = request(tool="shell.run", allow_always=False)

    assert await ask_and_answer(broker, published, "always", ineligible) is True

    assert policy_bytes(root) == before
    asking = asyncio.create_task(broker.ask(request("t1", "shell.run", False)))
    await pending(published, 2)
    broker.answer("t1", "deny")
    assert await asking is False


async def test_write_failure_publishes_an_error_and_still_allows(root):
    broker, published = make(root)
    folder = root / "agents" / "edith"
    before = policy_bytes(root)
    folder.chmod(0o500)
    try:
        assert await ask_and_answer(broker, published, "always") is True
    finally:
        folder.chmod(0o700)

    [error] = [event for event in published if event["type"] == "error"]
    assert "agents/edith/policy.yaml" in error["message"]
    assert policy_bytes(root) == before


async def test_cancel_answers_no(root):
    broker, published = make(root)
    asking = asyncio.create_task(broker.ask(request()))
    await pending(published)

    broker.cancel()

    assert await asking is False


async def test_cancel_without_pending_is_harmless(root):
    broker, _ = make(root)

    broker.cancel()


async def test_integration_with_edith_audits_the_user_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    home, notes = make_viernes_home(tmp_path)
    published = []
    loop = asyncio.get_running_loop()

    def publish(event):
        published.append(event)
        if event["type"] == "needs_confirmation":
            loop.call_soon(broker.answer, event["task_id"], "allow")

    broker = ConfirmationBroker(home, "edith", publish)
    engine = FakeModelEngine(
        [CallTool(DELETE, {"path": "a.md"}), Final(structured={"resumen": "borrada"})]
    )
    deps = RunDeps(root=home, engine=engine, environ={}, confirmer=broker, publish=publish)

    result = await run_task("viernes", TaskRequest(objetivo="Borra a.md"), deps)

    assert result.errores == []
    assert not (notes / "a.md").exists()
    [line] = [json.loads(raw) for raw in (home / "logs" / "audit.jsonl").read_text().splitlines()]
    assert (line["verdict"], line["user_decision"]) == ("confirm", "allow")
