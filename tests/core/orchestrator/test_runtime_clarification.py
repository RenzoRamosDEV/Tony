import asyncio

import pytest

from tests.core.orchestrator.skills_home import set_native
from tests.core.orchestrator.test_runtime import DONE, Harness, home_for
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final

ASK = CallTool("tony.ask_user", {"question": "¿Qué cuenta?", "options": ["Personal", "Trabajo"]})
DELETE = CallTool("filesystem.delete_file", {"path": "a.md"})


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def delegating_home(tmp_path):
    home, notes = home_for(tmp_path)
    set_native(home, "viernes", ["ask_user"])
    chat = FakeChatEngine(
        [CallTool("tony.delegate", {"objetivo": "Manda el correo"}), Say("Hecho")]
    )
    return home, notes, chat


async def test_task_asks_and_the_answer_completes_it(tmp_path):
    home, _, chat = delegating_home(tmp_path)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Manda el correo")
        [asked] = await harness.wait_for("clarification_requested")
        harness.send(type="answer_clarification", request_id=asked["request_id"], answer="Trabajo")
        await harness.wait_for("result", 2)

    assert (asked["agent"], asked["question"], asked["options"]) == (
        "viernes",
        "¿Qué cuenta?",
        ["Personal", "Trabajo"],
    )
    assert asked["task_id"]
    assert [reply.text for reply in worker.replies] == ["Trabajo"]
    assert harness.of("needs_confirmation") == []


async def test_wrong_request_id_is_ignored(tmp_path):
    home, _, chat = delegating_home(tmp_path)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Manda el correo")
        [asked] = await harness.wait_for("clarification_requested")
        harness.send(type="answer_clarification", request_id="otro", answer="x")
        await asyncio.sleep(0.1)
        assert worker.replies == []
        harness.send(type="answer_clarification", request_id=asked["request_id"], answer="ok")
        await harness.wait_for("result", 2)

    assert [reply.text for reply in worker.replies] == ["ok"]


async def test_confirm_does_not_resolve_a_question_and_an_answer_does_not_approve(tmp_path):
    home, notes, chat = delegating_home(tmp_path)
    worker = FakeModelEngine([ASK, DELETE, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Manda el correo")
        [asked] = await harness.wait_for("clarification_requested")
        harness.send(type="confirm", task_id=asked["task_id"], decision="allow")
        await asyncio.sleep(0.1)
        assert worker.replies == []

        harness.send(type="answer_clarification", request_id=asked["request_id"], answer="sí")
        [request] = await harness.wait_for("needs_confirmation")
        harness.send(type="answer_clarification", request_id=asked["request_id"], answer="sí")
        await asyncio.sleep(0.1)
        assert (notes / "a.md").exists()

        harness.send(type="confirm", task_id=request["task_id"], decision="allow")
        await harness.wait_for("result", 2)

    assert not (notes / "a.md").exists()


async def test_cancel_ends_the_wait_and_the_task(tmp_path):
    home, _, chat = delegating_home(tmp_path)
    worker = FakeModelEngine([ASK, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        cancels = []
        broker = harness.runtime.clarifications
        original = broker.cancel
        broker.cancel = lambda: (cancels.append(1), original())
        harness.send(type="send_message", text="Manda el correo")
        await harness.wait_for("clarification_requested")
        harness.send(type="cancel")
        [task_result] = [event for event in await harness.wait_for("result") if "outcome" in event]

    assert cancels == [1]
    assert task_result["outcome"] == "cancelled"


async def test_invalid_command_error_does_not_echo_the_answer(tmp_path):
    home, _, _ = delegating_home(tmp_path)

    async with Harness(home) as harness:
        harness.send(type="answer_clarification", request_id="r", answer="hunter2", x="hunter2")
        [error] = await harness.wait_for("error")

    assert "answer_clarification" in error["message"] and "hunter2" not in str(error)
