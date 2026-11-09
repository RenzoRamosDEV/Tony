import pytest

from tests.core.orchestrator.test_runtime import Harness, home_for
from tests.fakes.fake_chat import FakeChatEngine

home_dir = pytest.fixture(autouse=True)(
    lambda tmp_path, monkeypatch: monkeypatch.setenv("HOME", str(tmp_path))
)


def seed(harness, conversation_id, *texts):
    for text in texts:
        harness.runtime.history.add(conversation_id, "user", "jarvis", text)


def items(event):
    return [(item["id"], item["message_count"]) for item in event["items"]]


async def test_list_conversations_publishes_one_event_newest_first(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        seed(harness, "a", "uno", "dos")
        seed(harness, "b", "tres")
        harness.send(type="list_conversations")
        [event] = await harness.wait_for("conversations")

    assert items(event) == [("b", 1), ("a", 2)]


async def test_resume_stores_later_messages_under_the_id(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        seed(harness, "old", "antes")
        harness.send(type="resume_conversation", id="old")
        harness.send(type="send_message", text="sigamos")
        await harness.wait_for("result")
        stored = [m.content for m in harness.runtime.history.recent("old")]

    assert stored == ["antes", "sigamos", "ok"]


async def test_resume_changes_only_the_conversation_id(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        seed(harness, "old", "antes")
        runtime = harness.runtime
        session, broker = runtime.session, runtime.broker
        status = session.status
        harness.send(type="resume_conversation", id="old")
        harness.send(type="list_conversations")
        await harness.wait_for("conversations")

        assert runtime.conversation.conversation_id == "old"
        assert (runtime.session, runtime.broker, session.status) == (session, broker, status)
        assert harness.of("needs_confirmation") == []
        assert harness.of("token") == [] and harness.of("result") == []


async def test_resume_unknown_id_publishes_an_error_and_keeps_the_current_id(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        current = harness.runtime.conversation.conversation_id
        harness.send(type="resume_conversation", id="nope")
        [error] = await harness.wait_for("error")

        assert error["source"] == "resume_conversation"
        assert "nope" in error["message"]
        assert harness.runtime.conversation.conversation_id == current


async def test_delete_removes_the_conversation_and_republishes_the_list(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        seed(harness, "a", "uno")
        seed(harness, "b", "dos")
        harness.send(type="delete_conversation", id="a")
        [event] = await harness.wait_for("conversations")

    assert items(event) == [("b", 1)]


async def test_delete_unknown_id_publishes_an_error_and_no_list(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home, FakeChatEngine()) as harness:
        seed(harness, "a", "uno")
        harness.send(type="delete_conversation", id="nope")
        [error] = await harness.wait_for("error")

        assert error["source"] == "delete_conversation"
        assert harness.of("conversations") == []
        assert harness.runtime.history.has_conversation("a")
