import asyncio
import json

import pytest

from tests.core.guard.shipped_policy import SHIPPED_POLICY_YAML
from tests.core.orchestrator.tony_home import make_tony_home
from tests.fakes.changes import FakeChanges
from tests.fakes.fake_chat import FakeChatEngine, Say
from tests.fakes.fake_engine import CallTool, FakeModelEngine, Final
from tests.fakes.servers import fake_fs_entry
from tony.core.orchestrator.runtime import CoreRuntime

NO_PIN = SHIPPED_POLICY_YAML.replace("pin_required: true", "pin_required: false")
NO_READ = NO_PIN.replace(
    "rules:\n", 'rules:\n  - match: "filesystem.read_*"\n    verdict: deny\n    id: no-read\n', 1
)
DONE = {"resumen": "hecho", "datos": None, "pasos": [], "errores": []}
POLICY = "agents/edith/policy.yaml"
VIERNES_TOOLS = "agents/viernes/tool/tool.json"
READ = CallTool("filesystem.read_file", {"path": "a.md"})


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def delegate(objetivo="Lee a.md"):
    return [CallTool("tony.delegate", {"objetivo": objetivo}), Say("Hecho")]


class Harness:
    def __init__(self, home, chat, worker):
        self.events = []
        self.changes = FakeChanges()
        self.runtime = CoreRuntime(
            home,
            self.events.append,
            chat_engine=chat,
            engine=worker,
            environ={},
            changes=self.changes,
        )

    async def __aenter__(self):
        self.serving = asyncio.create_task(self.runtime.serve())
        await self.until(lambda: any(e["type"] == "reply_mode" for e in self.events))
        return self

    async def __aexit__(self, *exc_info):
        if not self.serving.done():
            self.runtime.submit({"type": "stop"})
        await asyncio.wait_for(self.serving, 5)

    async def until(self, predicate, timeout=5.0):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    def of(self, kind):
        return [event for event in self.events if event["type"] == kind]

    async def turn(self, text, count):
        self.runtime.submit({"type": "send_message", "text": text})
        await self.until(
            lambda: len([e for e in self.of("result") if e["scope"] == "turn"]) >= count
        )


def audit(home):
    lines = (home / "logs" / "audit.jsonl").read_text().splitlines()
    return [(line["tool"], line["verdict"], line["rule"]) for line in map(json.loads, lines)]


async def test_policy_edit_applies_to_next_call_without_restart(tmp_path):
    home, _ = make_tony_home(tmp_path, policy=NO_PIN)
    chat = FakeChatEngine(delegate(), delegate())
    worker = FakeModelEngine([READ, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        await harness.turn("uno", 1)
        (home / POLICY).write_text(NO_READ)
        await harness.changes.push(home / POLICY)
        await harness.turn("dos", 2)

    assert audit(home) == [
        ("filesystem.read_file", "allow", "filesystem.read_*/allow"),
        ("filesystem.read_file", "deny", "no-read"),
    ]


async def test_invalid_policy_published_and_previous_kept(tmp_path):
    home, _ = make_tony_home(tmp_path, policy=NO_PIN)
    chat = FakeChatEngine(delegate())
    worker = FakeModelEngine([READ, Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        (home / POLICY).write_text("default: [roto\n")
        await harness.changes.push(home / POLICY)
        await harness.turn("uno", 1)

    errors = [e for e in harness.of("error") if e["source"] == "reload"]
    assert len(errors) == 1 and POLICY in errors[0]["message"]
    assert audit(home) == [("filesystem.read_file", "allow", "filesystem.read_*/allow")]


async def test_tool_json_change_used_by_next_task_and_turn(tmp_path):
    home, notes = make_tony_home(tmp_path, policy=NO_PIN)
    chat = FakeChatEngine(delegate(), delegate())
    worker = FakeModelEngine([Final(structured=DONE)])

    async with Harness(home, chat, worker) as harness:
        await harness.turn("uno", 1)
        first_offer = list(worker.offered)
        tool_json = home / VIERNES_TOOLS
        data = json.loads(tool_json.read_text())
        data["mcpServers"]["notas"] = fake_fs_entry(str(notes))
        tool_json.write_text(json.dumps(data))
        jarvis_tools = home / "agents/jarvis/tool/tool.json"
        jarvis_tools.write_text(json.dumps({"mcpServers": {}, "native": ["read_skill"]}))
        await harness.changes.push(tool_json, jarvis_tools)
        await harness.until(
            lambda: any(
                e["type"] == "mcp_status" and e["server"] == "notas" for e in harness.events
            )
        )
        await harness.turn("dos", 2)

    assert "notas.read_file" not in first_offer
    assert "notas.read_file" in worker.offered
    assert "tony.read_skill" not in chat.offered[0]
    assert "tony.read_skill" in chat.offered[1]


async def test_stop_stops_the_reloader(tmp_path):
    home, _ = make_tony_home(tmp_path, policy=NO_PIN)
    before = set(asyncio.all_tasks())

    async with Harness(home, FakeChatEngine(), FakeModelEngine([])) as harness:
        assert harness.changes.started == [(home, "edith")]

    assert harness.changes.stop.is_set()
    assert harness.changes.closed
    assert set(asyncio.all_tasks()) - before == set()
