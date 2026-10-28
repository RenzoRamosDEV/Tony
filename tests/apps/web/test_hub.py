"""ConversationHub (design.md D4): hello decisions, one socket, turns, modes, cancel, close."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.apps.web.helpers import Doubles, FakeSocket, delegating
from tony.apps.web.hub import ConversationHub, HubState, decide_hello
from tony.apps.web.protocol import ClientMessage
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.task import TaskStatus


class HubHarness:
    def __init__(self, tmp_path: Path, turns: list | None = None) -> None:
        self.d = Doubles(tmp_path, turns)
        self.hub = ConversationHub(self.d.clock)

    async def start(self) -> ConversationHub:
        runtime = await self.d.build(self.hub.gate_factory)
        self.hub.bind(runtime)
        return self.hub

    @property
    def clock(self):
        return self.d.clock

    async def hello(self, socket: FakeSocket, conversation_id=None, last_seq: int = 0) -> str:
        await self.hub.dispatch(
            socket,
            ClientMessage("hello", {"conversation_id": conversation_id, "last_seq": last_seq}, 1),
        )
        await self.clock.settle()
        return (
            socket.last("hello.ok")["payload"]["conversation_id"]
            if socket.of_type("hello.ok")
            else ""
        )

    async def send(self, socket: FakeSocket, type_: str, payload: dict) -> None:
        await self.hub.dispatch(socket, ClientMessage(type_, payload, 1))
        await self.clock.settle()


@pytest.fixture
async def h(tmp_path: Path):
    harness = HubHarness(tmp_path, [{"display_text": "Hola.", "speech_text": None}])
    await harness.start()
    yield harness
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_hello_null_creates_a_web_conversation_and_answers_hello_ok(h: HubHarness) -> None:
    socket = FakeSocket()

    conversation = await h.hello(socket)

    ok = socket.sent[0]
    assert ok["type"] == "hello.ok" and ok["seq"] == 0 and ok["conversation_id"] == conversation
    assert ok["payload"] == {
        "conversation_id": conversation,
        "reply_mode": "auto",
        "last_seq": 0,
        "state": {"turn_in_progress": False, "active_tasks": [], "pending_confirmation": None},
    }
    listed = h.hub.runtime.memory.conversations.list_conversations()
    assert [c.channel for c in listed] == ["web"]
    assert (
        h.hub.runtime.session is not None and h.hub.runtime.session.conversation_id == conversation
    )


async def test_hello_reopens_an_existing_conversation_and_rejects_unknown_ids(
    h: HubHarness,
) -> None:
    store = h.hub.runtime.memory.conversations
    existing = store.start_conversation("cli")
    store.add_message(existing, "user", "antes", None)
    socket = FakeSocket()

    await h.send(socket, "hello", {"conversation_id": "nope"})
    assert socket.types() == ["error"] and socket.closed == []
    assert socket.sent[0]["payload"]["code"] == "unknown_conversation"

    conversation = await h.hello(socket, existing)

    assert conversation == existing
    assert [m.content for m in store.messages(existing)] == ["antes"]


async def test_second_socket_on_the_same_conversation_is_busy_and_closed_1008(
    h: HubHarness,
) -> None:
    first, second = FakeSocket(), FakeSocket()
    conversation = await h.hello(first)

    await h.send(second, "hello", {"conversation_id": conversation})

    assert second.sent[-1]["type"] == "error"
    assert second.sent[-1]["payload"]["code"] == "conversation_busy"
    assert second.closed == [1008]
    await h.send(first, "user.text", {"text": "hola"})
    assert "assistant.final" in first.types() and second.types() == ["error"]


async def test_socket_relay_after_detach(h: HubHarness) -> None:
    first, second = FakeSocket(), FakeSocket()
    conversation = await h.hello(first)

    h.hub.detach(first)
    assert await h.hello(second, conversation) == conversation
    await h.send(second, "user.text", {"text": "hola"})

    assert "assistant.final" in second.types() and first.types() == ["hello.ok"]


async def test_hello_for_another_conversation_switches_only_when_idle(h: HubHarness) -> None:
    store = h.hub.runtime.memory.conversations
    first, second = FakeSocket(), FakeSocket()
    c1 = await h.hello(first)
    c2 = store.start_conversation("web")

    await h.send(second, "hello", {"conversation_id": c2})
    assert second.sent[-1]["payload"]["code"] == "conversation_busy" and second.closed == []
    assert h.hub.conversation_id == c1

    h.hub.detach(first)
    assert await h.hello(second, c2) == c2
    assert h.hub.conversation_id == c2 and h.hub.runtime.session.conversation_id == c2
    assert h.d.runner.opened and len(h.d.runner.opened) == 2


async def test_hello_for_another_conversation_is_busy_while_a_task_runs(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [delegating("larga")])
    await harness.start()
    harness.d.scripts["larga"] = [("sleep", 100)]
    store = harness.hub.runtime.memory.conversations
    first, second = FakeSocket(), FakeSocket()
    c1 = await harness.hello(first)
    await harness.send(first, "user.text", {"text": "tarea"})
    harness.hub.detach(first)
    c2 = store.start_conversation("web")

    await harness.send(second, "hello", {"conversation_id": c2})

    assert second.sent[-1]["payload"]["code"] == "conversation_busy"
    assert harness.hub.conversation_id == c1
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_user_text_rejections(h: HubHarness) -> None:
    socket = FakeSocket()
    await h.hello(socket)

    await h.send(socket, "user.text", {"text": "   "})
    assert socket.sent[-1]["payload"]["code"] == "empty_text"
    assert h.d.runner.prompts == []


async def test_user_text_during_a_turn_is_rejected(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [delegating("larga"), "Segunda."])
    await harness.start()
    harness.d.scripts["larga"] = [("sleep", 5)]
    socket = FakeSocket()
    await harness.hello(socket)

    await harness.send(socket, "user.text", {"text": "tarea"})
    await harness.send(socket, "user.text", {"text": "otra"})

    assert socket.sent[-1]["payload"]["code"] == "turn_in_progress"
    assert harness.d.runner.prompts[-1].endswith("tarea") and len(harness.d.runner.prompts) == 1
    await harness.clock.advance(5)
    assert "assistant.final" in socket.types()
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_set_mode_persists_or_rejects(h: HubHarness) -> None:
    socket = FakeSocket()
    await h.hello(socket)
    settings_path = h.hub.runtime.memory.settings.path

    await h.send(socket, "set_mode", {"reply_mode": "text"})
    assert json.loads(settings_path.read_text()) == {"reply_mode": "text"}
    assert socket.types() == ["hello.ok"]

    await h.send(socket, "set_mode", {"reply_mode": "loud"})
    assert socket.sent[-1]["payload"]["code"] == "invalid_reply_mode"
    assert json.loads(settings_path.read_text()) == {"reply_mode": "text"}
    await h.send(socket, "set_mode", {})
    assert socket.sent[-1]["payload"]["code"] == "invalid_reply_mode"


async def test_cancel_reaches_the_active_task_and_rejects_unknown_ids(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [delegating("larga")])
    await harness.start()
    harness.d.scripts["larga"] = [("sleep", 100)]
    socket = FakeSocket()
    await harness.hello(socket)
    await harness.send(socket, "user.text", {"text": "tarea"})
    task_id = socket.last("task.running")["task_id"]

    await harness.send(socket, "cancel", {"task_id": "nope"})
    assert socket.sent[-1]["payload"]["code"] == "unknown_task"
    assert socket.sent[-1]["conversation_id"] == harness.hub.conversation_id
    assert "nope" in socket.sent[-1]["payload"]["detail"]

    await harness.send(socket, "cancel", {"task_id": task_id})
    await harness.clock.settle()
    assert socket.last("task.cancelled")["payload"] == {"reason": "user"}
    assert socket.last("task.result")["payload"]["result"]["status"] == "cancelled"
    assert harness.d.runner.interrupts == 1
    assert "assistant.final" in socket.types()
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_hello_required_before_any_other_message(h: HubHarness) -> None:
    socket = FakeSocket()

    await h.send(socket, "user.text", {"text": "hola"})

    assert socket.sent == [
        {
            "v": 1,
            "type": "error",
            "seq": 0,
            "conversation_id": None,
            "payload": {"code": "hello_required", "detail": socket.sent[0]["payload"]["detail"]},
        }
    ]
    assert h.d.runner.prompts == []


async def test_reconnect_replays_after_last_seq_with_state(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [delegating("confirma")])
    await harness.start()
    harness.d.scripts["confirma"] = [
        *[("tool", f"fs.read{i}", {}) for i in range(5)],
        ("confirm", "fs.write", {"p": 1}),
    ]
    first = FakeSocket()
    conversation = await harness.hello(first)
    await harness.send(first, "user.text", {"text": "escribe"})
    seqs = [m["seq"] for m in first.sent if m["seq"]]
    assert len(seqs) >= 20 and seqs == sorted(seqs)
    harness.hub.detach(first)
    await harness.clock.advance(20)

    second = FakeSocket()
    await harness.hello(second, conversation, last_seq=18)

    ok = second.sent[0]["payload"]
    # The wait phrase (3 s) was published while nobody listened: it is replayed too.
    assert ok["last_seq"] == seqs[-1] + 1 and "resync" not in ok
    assert [m["seq"] for m in second.sent[1:]] == list(range(19, ok["last_seq"] + 1))
    assert second.last("assistant.wait")["payload"] == {"text": "Dame un momento."}
    task_id = first.last("task.queued")["task_id"]
    assert ok["state"]["turn_in_progress"] is True
    assert ok["state"]["active_tasks"] == [
        {"task_id": task_id, "parent_id": None, "status": "waiting_confirmation"}
    ]
    pending = ok["state"]["pending_confirmation"]
    assert pending["tool"] == "fs.write" and pending["args"] == {"p": 1}
    assert 39 <= pending["expires_in_s"] <= 40
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_reconnect_too_old_requests_a_resync(h: HubHarness) -> None:
    socket = FakeSocket()
    conversation = await h.hello(socket)
    for i in range(700):
        await h.hub.stream.publish("task.progress", {"i": i})
    h.hub.detach(socket)

    second = FakeSocket()
    await h.hello(second, conversation, last_seq=10)

    assert second.sent[0]["payload"]["resync"] is True
    assert len(second.sent) == 1


async def test_aclose_closes_socket_cancels_tasks_and_closes_the_session(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [delegating("larga")])
    await harness.start()
    harness.d.scripts["larga"] = [("sleep", 100)]
    socket = FakeSocket()
    await harness.hello(socket)
    await harness.send(socket, "user.text", {"text": "tarea"})
    task = next(iter(harness.hub.runtime.orchestrator.tasks.values()))

    await asyncio.wait_for(harness.hub.aclose(), 2)

    assert socket.closed == [1001]
    assert harness.hub.socket is None and harness.hub.turn is not None
    assert task.status == TaskStatus.CANCELLED
    assert harness.d.runner.closed is True and harness.hub.runtime.session is None
    await harness.hub.runtime.aclose()


async def test_unexpected_turn_failure_is_reported_and_unblocks(tmp_path: Path) -> None:
    async def dying(prompt, handlers):
        raise ConnectionError("cli died")

    harness = HubHarness(tmp_path, [dying, "Sigo."])
    await harness.start()
    socket = FakeSocket()
    await harness.hello(socket)

    await harness.send(socket, "user.text", {"text": "hola"})

    assert socket.last("error")["payload"]["code"] == "turn_failed"
    assert "cli died" in socket.last("error")["payload"]["detail"]
    assert "assistant.final" in socket.types()
    await harness.send(socket, "user.text", {"text": "otra"})
    assert socket.last("assistant.final")["payload"]["display_text"] == "Sigo."
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


@pytest.mark.parametrize(
    ("state", "requested", "exists", "expected"),
    [
        (HubState(None, False, False), None, False, "open"),
        (HubState(None, False, False), "c2", True, "open"),
        (HubState(None, False, False), "c2", False, "unknown"),
        (HubState("c1", False, False), "c1", True, "attach"),
        (HubState("c1", True, False), "c1", True, "busy_same"),
        (HubState("c1", True, True), "c1", True, "busy_same"),
        (HubState("c1", False, False), "c2", True, "switch"),
        (HubState("c1", False, False), None, True, "switch"),
        (HubState("c1", True, False), "c2", True, "busy_other"),
        (HubState("c1", False, True), "c2", True, "busy_other"),
        (HubState("c1", False, True), None, True, "busy_other"),
        (HubState("c1", True, False), "c2", False, "unknown"),
        (HubState("c1", False, False), "c3", False, "unknown"),
    ],
)
def test_decide_hello(state: HubState, requested, exists: bool, expected: str) -> None:
    assert decide_hello(state, requested, exists) == expected


async def test_user_text_without_text_field_is_empty(h: HubHarness) -> None:
    socket = FakeSocket()
    await h.hello(socket)

    await h.send(socket, "user.text", {})

    assert socket.sent[-1]["payload"]["code"] == "empty_text"
    assert h.d.runner.prompts == []


async def test_hello_without_last_seq_replays_from_the_start(h: HubHarness) -> None:
    first = FakeSocket()
    conversation = await h.hello(first)
    await h.hub.stream.publish("task.progress", {"i": 1})
    h.hub.detach(first)
    second = FakeSocket()

    await h.hub.dispatch(second, ClientMessage("hello", {"conversation_id": conversation}, 1))
    await h.clock.settle()

    assert [m["seq"] for m in second.sent] == [0, 1]


async def test_a_socket_that_fails_to_send_is_detached(h: HubHarness) -> None:
    socket = FakeSocket()
    await h.hello(socket)
    socket.closed.append(1006)

    await h.hub.stream.publish("task.progress", {"i": 1})
    await h.clock.settle()

    assert h.hub.socket is None


async def test_front_tool_confirmation_flows_through_the_hub(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [])
    await harness.start()
    gate = harness.d.gate

    async def asking_turn(prompt, handlers):
        approved = await gate.confirm(ConfirmRequest.create("front", "fake.destroy", {"k": 1}))
        return {"display_text": f"aprobado: {approved}", "speech_text": None}

    harness.d.runner.turns.append(asking_turn)
    socket = FakeSocket()
    await harness.hello(socket)
    await harness.send(socket, "user.text", {"text": "destruye"})
    asked = socket.last("task.needs_confirmation")
    assert asked["task_id"] == "front" and asked["payload"]["tool"] == "fake.destroy"
    assert asked["payload"]["expires_in_s"] == 60

    await harness.send(
        socket,
        "confirm",
        {"confirmation_id": asked["payload"]["confirmation_id"], "approved": True},
    )

    assert socket.last("task.confirmed")["task_id"] == "front"
    assert socket.last("assistant.final")["payload"]["display_text"] == "aprobado: True"
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()


async def test_front_tool_confirmation_expires_with_the_clock(tmp_path: Path) -> None:
    harness = HubHarness(tmp_path, [])
    await harness.start()
    gate = harness.d.gate

    async def asking_turn(prompt, handlers):
        approved = await gate.confirm(ConfirmRequest.create("front", "fake.destroy", {}))
        return {"display_text": f"aprobado: {approved}", "speech_text": None}

    harness.d.runner.turns.append(asking_turn)
    socket = FakeSocket()
    await harness.hello(socket)
    await harness.send(socket, "user.text", {"text": "destruye"})
    assert socket.of_type("task.needs_confirmation")

    await harness.clock.advance(60)

    assert socket.last("task.cancelled")["task_id"] == "front"
    assert socket.last("assistant.final")["payload"]["display_text"] == "aprobado: False"
    await harness.hub.aclose()
    await harness.hub.runtime.aclose()
