"""Builders for the web tests: runtime of doubles, fake socket, keyed scripted runners."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from tests.apps.cli_helpers import FakeManager, write_agent
from tests.fakes.clock import FakeClock
from tests.fakes.conversation import FakeConversationRunner, ScriptedTurn
from tests.fakes.fake_watch import ScriptedWatch
from tests.fakes.scripted_runner import ScriptedRunner, Step
from tony.core.channels.bootstrap import ChatRuntime, RuntimeOptions, build_chat_runtime
from tony.core.loader import AgentSpec
from tony.core.mcp import ToolCatalog
from tony.core.runner import EventSink, TaskRequest, TaskResult

ORIGIN = "http://127.0.0.1:8787"


def write_front(agents_dir: Path, name: str = "jarvis") -> None:
    write_agent(agents_dir, name, "front", model="claude-haiku")
    tool_dir = agents_dir / name / "tool"
    tool_dir.mkdir(exist_ok=True)
    (tool_dir / "tool.json").write_text(
        json.dumps({"native": ["delegate", "remember", "set_reply_mode"]}), encoding="utf-8"
    )


def write_worker(agents_dir: Path, name: str = "viernes") -> None:
    write_agent(agents_dir, name, "worker")
    write_agent(agents_dir / name / "subagents", "investigador", "worker")
    tool_dir = agents_dir / name / "tool"
    tool_dir.mkdir(exist_ok=True)
    (tool_dir / "tool.json").write_text(json.dumps({"native": ["run_subagent"]}), encoding="utf-8")


class KeyedRunner:
    """AgentRunner that picks its script by `objetivo` when it runs; `subtask` steps delegate."""

    def __init__(
        self,
        task_id: str,
        scripts: dict[str, list[Step]],
        clock: FakeClock,
        token,
        gate,
        call,
        handlers,
    ) -> None:
        self.task_id = task_id
        self.scripts = scripts
        self.clock = clock
        self.token = token
        self.gate = gate
        self.call = call
        self.handlers = handlers
        self.inner: ScriptedRunner | None = None

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        script = list(self.scripts.get(request.objetivo, []))
        plain = [step for step in script if step[0] != "subtask"]
        usage = next((step[1] for step in script if step[0] == "usage"), None)
        plain = [step for step in plain if step[0] != "usage"]
        self.inner = ScriptedRunner(
            self.task_id,
            plain,
            cancel_token=self.token,
            clock=self.clock,
            call=self.call,
            gate=self.gate,
            usage=usage,
        )
        for step in script:
            if step[0] == "subtask":
                await self.handlers.run_subagent(step[1], TaskRequest(objetivo=step[2]))
        return await self.inner.run(spec, request, tools, events)


class Doubles:
    def __init__(self, tmp_path: Path, turns: list[ScriptedTurn] | None = None) -> None:
        self.root = tmp_path
        self.clock = FakeClock()
        self.runner = FakeConversationRunner(list(turns or []))
        self.managers: list[FakeManager] = []
        self.scripts: dict[str, list[Step]] = {}
        self.runners: list[KeyedRunner] = []
        self.watch = ScriptedWatch()
        self.gate: Any = None
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "tony.yaml").write_text("", encoding="utf-8")
        write_front(tmp_path / "agents")
        write_worker(tmp_path / "agents")

    def settings_yaml(self, text: str) -> None:
        (self.root / "config" / "tony.yaml").write_text(text, encoding="utf-8")

    def options(self) -> RuntimeOptions:
        return RuntimeOptions(
            config_path=self.root / "config" / "tony.yaml",
            agents_dir=self.root / "agents",
            logs_dir=self.root / "logs",
            memory_dir=self.root / "memory",
        )

    def manager_factory(self, settings) -> FakeManager:
        manager = FakeManager()
        self.managers.append(manager)
        return manager

    def runner_factory(self, settings, task_id, gate, call, token, handlers=None) -> KeyedRunner:
        runner = KeyedRunner(task_id, self.scripts, self.clock, token, gate, call, handlers)
        self.runners.append(runner)
        return runner

    def conversation_factory(self, settings, gate, call) -> FakeConversationRunner:
        self.gate = gate
        return self.runner

    async def build(self, gate_factory) -> ChatRuntime:
        return await build_chat_runtime(
            self.options(),
            gate_factory=gate_factory,
            conversation_factory=self.conversation_factory,
            manager_factory=self.manager_factory,
            runner_factory=self.runner_factory,
            watch=self.watch,
            clock=self.clock,
        )


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed: list[int] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def send_text(self, text: str) -> None:
        await self.gate.wait()
        if self.closed:
            raise RuntimeError("socket cerrado")
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.closed.append(code)

    def types(self) -> list[str]:
        return [m["type"] for m in self.sent]

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == type_]

    def last(self, type_: str) -> dict[str, Any]:
        return self.of_type(type_)[-1]


def delegating(objetivo: str):
    async def turn(prompt: str, handlers: Any) -> dict[str, Any]:
        result = await handlers.delegate(TaskRequest(objetivo=objetivo))
        return {"display_text": f"Resultado: {result.resumen}", "speech_text": None}

    return turn


# --- FastAPI app over the runtime of doubles -----------------------------------------------------

from collections.abc import Callable, Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from tony.apps.web.hub import ConversationHub  # noqa: E402
from tony.apps.web.options import WebOptions  # noqa: E402
from tony.apps.web.server import create_app  # noqa: E402
from tony.core.channels.bootstrap import ChatRuntime as _Runtime  # noqa: E402


def build_test_app(
    tmp_path: Path,
    *,
    turns: list[ScriptedTurn] | None = None,
    scripts: dict[str, list[Step]] | None = None,
    settings_yaml: str = "",
    dist: Path | None = None,
    open_url: Callable[[str], Any] | None = None,
    open_browser: bool = False,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> TestClient:
    """TestClient whose startup builds the runtime of doubles; `app.state` exposes them."""
    doubles = Doubles(tmp_path, turns)
    doubles.scripts.update(scripts or {})
    if settings_yaml:
        doubles.settings_yaml(settings_yaml)
    hub = ConversationHub(doubles.clock)

    async def boot() -> tuple[ConversationHub, _Runtime]:
        runtime = await doubles.build(hub.gate_factory)
        hub.bind(runtime)
        return hub, runtime

    options = WebOptions(host, port, doubles.options(), open_browser=open_browser, dist_dir=dist)
    app = create_app(boot, options, open_url=open_url or (lambda url: None))
    app.state.doubles = doubles
    app.state.clock = doubles.clock
    app.state.runner = doubles.runner
    app.state.scripts = doubles.scripts
    client = TestClient(app, headers={"Origin": ORIGIN})
    return client


def advance(client: TestClient, seconds: float) -> None:
    assert client.portal is not None
    client.portal.call(client.app.state.clock.advance, seconds)


def settle(client: TestClient) -> None:
    assert client.portal is not None
    client.portal.call(client.app.state.clock.settle)


# --- WebSocket helpers ---------------------------------------------------------------------


def hello(ws: Any, conversation_id: str | None = None, last_seq: int = 0) -> dict[str, Any]:
    payload = {"conversation_id": conversation_id, "last_seq": last_seq}
    ws.send_json({"v": 1, "type": "hello", "seq": 1, "conversation_id": None, "payload": payload})
    return ws.receive_json()


@contextmanager
def open_chat(client: TestClient, conversation_id: str | None = None) -> Iterator[tuple[Any, str]]:
    """Connected socket with an accepted hello, closed on exit even when the test fails."""
    with client.websocket_connect("/ws/chat") as ws:
        ok = hello(ws, conversation_id)
        assert ok["type"] == "hello.ok", ok
        yield ws, ok["payload"]["conversation_id"]


def send(ws: Any, type_: str, payload: dict[str, Any], seq: int = 2) -> None:
    ws.send_json({"v": 1, "type": type_, "seq": seq, "conversation_id": None, "payload": payload})


def drain_until(ws: Any, type_: str, limit: int = 200) -> list[dict[str, Any]]:
    """Receive envelopes until one of `type_` arrives (inclusive)."""
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        message = ws.receive_json()
        seen.append(message)
        if message["type"] == type_:
            return seen
    raise AssertionError(f"no llegó {type_}; recibidos: {[m['type'] for m in seen]}")


def wait_detached(client: TestClient) -> None:
    for _ in range(50):
        if client.app.state.hub.socket is None:
            return
        settle(client)
    raise AssertionError("el hub sigue con un socket activo")
