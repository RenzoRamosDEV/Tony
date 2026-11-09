import asyncio
import json

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.fake_chat import FakeChatEngine, Say, Wait
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final, Hang
from tests.fakes.processes import processes_mentioning
from tony.core.guard.pin import PinStore
from tony.core.memory.preferences import PREFERENCES_FILE
from tony.core.orchestrator.runtime import CoreRuntime

PIN = "4821"
NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")
DONE = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


class Harness:
    def __init__(self, home, chat=None, worker=None, clock=None, **options) -> None:
        self.events: list[dict] = []
        self.runtime = CoreRuntime(
            home,
            self.events.append,
            chat_engine=chat or FakeChatEngine(),
            engine=worker or FakeModelEngine([Final(structured=DONE)]),
            environ={},
            monotonic=clock or Clock(),
            **options,
        )
        self.serving: asyncio.Task | None = None

    async def __aenter__(self):
        self.serving = asyncio.create_task(self.runtime.serve())
        await self.until(lambda: any(e["type"] == "reply_mode" for e in self.events))
        return self

    async def __aexit__(self, *exc_info):
        if not self.serving.done():
            self.runtime.submit({"type": "stop"})
        await asyncio.wait_for(self.serving, 5)

    def send(self, **command):
        self.runtime.submit(command)

    async def until(self, predicate, timeout=5.0):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    def of(self, kind):
        return [event for event in self.events if event["type"] == kind]

    async def wait_for(self, kind, count=1):
        await self.until(lambda: len(self.of(kind)) >= count)
        return self.of(kind)


def home_for(tmp_path, policy=NO_PIN, **options):
    return make_tony_home(tmp_path, policy=policy, **options)


async def test_start_publishes_auth_reply_mode_and_probes_mcp_in_background(tmp_path):
    broken = {"broken": {"command": "/nonexistent/tony-no-such-cmd"}}
    home, notes = home_for(tmp_path, extra_servers=broken)

    async with Harness(home) as harness:
        statuses = await harness.wait_for("mcp_status", 2)

    [auth] = harness.of("auth")
    assert (auth["state"], auth["reason"]) == ("unlocked", "not_required")
    assert harness.of("reply_mode")[0]["mode"] == "auto"
    by_server = {event["server"]: event for event in statuses}
    assert (by_server["filesystem"]["agent"], by_server["filesystem"]["up"]) == ("viernes", True)
    assert by_server["broken"]["up"] is False
    assert processes_mentioning(str(notes)) == []


async def test_start_with_a_valid_lock_asks_for_the_pin(tmp_path):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)

    async with Harness(home) as harness:
        pass

    assert (harness.of("auth")[0]["state"], harness.of("auth")[0]["reason"]) == ("locked", "start")


async def test_slot_error_is_published_and_commands_keep_being_handled(tmp_path):
    home, _ = home_for(tmp_path)
    (home / "config").mkdir()
    (home / "config" / "tony.yaml").write_text("front: edith\n")
    events = []
    runtime = CoreRuntime(
        home, events.append, chat_engine=FakeChatEngine(), engine=None, environ={}
    )
    serving = asyncio.create_task(runtime.serve())

    runtime.submit({"type": "send_message", "text": "Hola"})
    runtime.submit({"type": "fly"})
    runtime.submit({"type": "stop"})
    await asyncio.wait_for(serving, 5)

    errors = [event for event in events if event["type"] == "error"]
    assert "config/tony.yaml" in errors[0]["message"]
    assert errors[1]["source"] == "send_message"
    assert "fly" in errors[2]["message"]


async def test_messages_are_answered_one_at_a_time_in_order(tmp_path):
    home, _ = home_for(tmp_path)
    release = asyncio.Event()
    chat = FakeChatEngine([Wait(release), Say("uno")], [Say("dos")])

    async with Harness(home, chat) as harness:
        harness.send(type="send_message", text="primero")
        harness.send(type="send_message", text="segundo")
        await asyncio.sleep(0.05)
        assert len(chat.prompts) == 1
        release.set()
        results = await harness.wait_for("result", 2)

    assert [event["text"] for event in results] == ["uno", "dos"]


async def test_set_mode_persists_and_publishes(tmp_path):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:
        harness.send(type="set_mode", mode="text")
        modes = await harness.wait_for("reply_mode", 2)

    assert modes[-1]["mode"] == "text"
    assert (home / PREFERENCES_FILE).read_text() == "reply_mode: text\n"


async def test_initial_mode_comes_from_preferences(tmp_path):
    home, _ = home_for(tmp_path)
    (home / "memory").mkdir()
    (home / PREFERENCES_FILE).write_text("reply_mode: voice\n")

    async with Harness(home) as harness:
        pass

    assert harness.of("reply_mode")[0]["mode"] == "voice"


async def test_confirm_is_routed_to_the_broker(tmp_path):
    home, notes = home_for(tmp_path)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("Hecho")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Borra a.md")
        [request] = await harness.wait_for("needs_confirmation")
        assert request["allow_always"] is True
        harness.send(type="confirm", task_id=request["task_id"], decision="allow")
        await harness.wait_for("result", 2)

    assert not (notes / "a.md").exists()


async def test_confirm_forwards_the_approval_id_to_the_broker(tmp_path):
    home, _ = home_for(tmp_path)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "Borra a.md"}), Say("Hecho")])
    worker = FakeModelEngine(
        [CallTool("filesystem.delete_file", {"path": "a.md"}), Final(structured=DONE)]
    )

    async with Harness(home, chat, worker) as harness:
        answers = []
        broker = harness.runtime.broker
        original = broker.answer
        broker.answer = lambda *args: (answers.append(args), original(*args))
        harness.send(type="send_message", text="Borra a.md")
        [request] = await harness.wait_for("needs_confirmation")
        harness.send(
            type="confirm",
            task_id=request["task_id"],
            decision="allow",
            approval_id=request["approval_id"],
        )
        await harness.wait_for("result", 2)

    assert answers == [(request["task_id"], "allow", request["approval_id"])]


async def test_wrong_pin_publishes_wrong_pin_and_correct_pin_unlocks(tmp_path):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)

    async with Harness(home) as harness:
        harness.send(type="unlock", pin="0000")
        harness.send(type="unlock", pin=PIN)
        auths = await harness.wait_for("auth", 3)

    assert [(event["state"], event["reason"]) for event in auths] == [
        ("locked", "start"),
        ("locked", "wrong_pin"),
        ("unlocked", "unlocked"),
    ]
    assert PIN not in json.dumps(harness.events)


async def test_unlock_null_enters_conversation_only_mode(tmp_path):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "x"}), Say("No puedo.")])

    async with Harness(home, chat) as harness:
        harness.send(type="unlock", pin=None)
        harness.send(type="send_message", text="Lista")
        await harness.wait_for("result")

    assert harness.of("auth")[-1]["reason"] == "cancelled"
    assert chat.replies[0].text == '{"error": "locked"}'


def idle_locked(tmp_path, chat):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)
    clock = Clock()
    return Harness(home, chat, clock=clock), clock


async def test_idle_locked_delegate_waits_for_unlock(tmp_path):
    chat = FakeChatEngine([Say("hola")], [CallTool("tony.delegate", {"objetivo": "x"}), Say("ok")])
    harness, clock = idle_locked(tmp_path, chat)

    async with harness:
        harness.send(type="unlock", pin=PIN)
        harness.send(type="send_message", text="uno")
        await harness.wait_for("result")
        clock.now += 31 * 60
        harness.send(type="send_message", text="dos")
        await harness.until(lambda: harness.of("auth")[-1]["reason"] == "idle")
        await asyncio.sleep(0.05)
        assert harness.of("task_started") == []
        harness.send(type="unlock", pin=PIN)
        await harness.wait_for("result", 3)

    assert harness.of("task_started")
    assert json.loads(chat.replies[0].text)["resumen"] == "hecho"


async def test_idle_locked_delegate_with_null_pin_is_refused(tmp_path):
    chat = FakeChatEngine([Say("hola")], [CallTool("tony.delegate", {"objetivo": "x"}), Say("ok")])
    harness, clock = idle_locked(tmp_path, chat)

    async with harness:
        harness.send(type="unlock", pin=PIN)
        harness.send(type="send_message", text="uno")
        await harness.wait_for("result")
        clock.now += 31 * 60
        harness.send(type="send_message", text="dos")
        await harness.until(lambda: harness.of("auth")[-1]["reason"] == "idle")
        harness.send(type="unlock", pin=None)
        await harness.wait_for("result", 2)

    assert chat.replies[0].text == '{"error": "locked"}'
    assert harness.of("task_started") == []


async def test_cancel_stops_the_turn_and_the_running_task(tmp_path):
    home, notes = home_for(tmp_path)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "x"}), Say("nunca")])
    worker = FakeModelEngine([CallTool("filesystem.list_directory", {"path": "."}), Hang()])

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Lista")
        await harness.until(lambda: worker.replies)
        harness.send(type="cancel")
        [result] = await harness.wait_for("result")
        harness.send(type="send_message", text="otra")
        await harness.until(lambda: len(chat.prompts) == 2)

    assert (result["scope"], result["outcome"]) == ("task", "cancelled")
    assert result["result"]["errores"] == ["tarea cancelada por el usuario"]
    assert not [e for e in harness.events if e["type"] == "token" and e["text"] == "nunca"]
    assert processes_mentioning(str(notes)) == []


async def test_exception_inside_a_handler_is_published_and_the_next_command_runs(
    tmp_path, monkeypatch
):
    home, _ = home_for(tmp_path)

    async with Harness(home) as harness:

        def boom(mode):
            raise OSError("disk full")

        monkeypatch.setattr(harness.runtime.conversation.preferences, "set_reply_mode", boom)
        harness.send(type="set_mode", mode="text")
        harness.send(type="send_message", text="Hola")
        await harness.wait_for("result")

    [error] = harness.of("error")
    assert (error["source"], error["message"]) == ("set_mode", "disk full")


async def test_stop_cancels_work_and_closes_history(tmp_path):
    home, notes = home_for(tmp_path)
    chat = FakeChatEngine([CallTool("tony.delegate", {"objetivo": "x"})])
    worker = FakeModelEngine([CallTool("filesystem.list_directory", {"path": "."}), Hang()])

    async with Harness(home, chat, worker) as harness:
        harness.send(type="send_message", text="Lista")
        await harness.until(lambda: worker.replies)

    assert harness.serving.done()
    assert processes_mentioning(str(notes)) == []
    with pytest.raises(Exception, match="closed"):
        harness.runtime.history.recent("x")


async def test_pin_never_published(tmp_path):
    home, _ = home_for(tmp_path, SHIPPED_POLICY_YAML)
    PinStore(home).set(PIN)

    async with Harness(home) as harness:
        harness.send(type="unlock", pin=9999)
        harness.send(type="unlock", pin="9999")
        await harness.wait_for("auth", 2)
        await harness.wait_for("error")

    assert "9999" not in json.dumps(harness.events)
