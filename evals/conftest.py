"""Eval harness: fixtures by default, the real model only with TONY_EVALS=1."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.fake_runner import FakeAgentRunner
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tests.fakes.worker_factory import FakeWorkerFactory
from tony.core.config import TonySettings, load_settings
from tony.core.evals.loader import load_conversation_evals, load_task_evals
from tony.core.evals.models import ConversationEval, TaskEval
from tony.core.evals.recorder import RecordingConversationRunner
from tony.core.evals.replay import ReplayConversationRunner, ReplayRunner
from tony.core.loader import AgentSpec, load_agent
from tony.core.logging import JsonlEventSink
from tony.core.mcp import McpManager, ToolCallOutcome, ToolCatalog
from tony.core.orchestrator.clock import SystemClock
from tony.core.orchestrator.worker import SdkWorkerFactory
from tony.core.runner import TaskResult
from tony.core.runner.claude_sdk import ClaudeSdkRunner
from tony.core.runner.conversation import ClaudeSdkConversation
from tony.core.runner.oneshot import one_shot
from tony.core.subagents.handlers import WorkerToolHandlers
from tony.core.subagents.launcher import SubagentLauncher

ROOT = Path(__file__).resolve().parents[1]
EVALS_DIR = ROOT / "evals"
FIXTURES_DIR = EVALS_DIR / "fixtures"
RUNS_DIR = EVALS_DIR / "runs"
LIVE = os.environ.get("TONY_EVALS") == "1"
NOTES = {"a.md": "hola mundo\n", "b.md": "lista de la compra: pan, leche\n", "tmp.md": "borrador\n"}
JUDGE_MODEL = "claude-haiku"


def task_evals() -> list[TaskEval]:
    return load_task_evals(EVALS_DIR / "tareas.yaml")


def conversation_evals() -> list[ConversationEval]:
    return load_conversation_evals(EVALS_DIR / "conversaciones.yaml")


def run_path(eval_id: str) -> Path:
    return RUNS_DIR / datetime.now(UTC).strftime("%Y%m%d") / f"{eval_id}.jsonl"


@pytest.fixture(scope="session")
def settings() -> TonySettings:
    return load_settings(ROOT / "config" / "tony.yaml")


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    notes = tmp_path / "notas"
    notes.mkdir()
    for name, text in NOTES.items():
        (notes / name).write_text(text, encoding="utf-8")
    return notes


@pytest.fixture
def agents_dir(tmp_path: Path, notes_dir: Path) -> Path:
    """The shipped agents, with viernes' filesystem MCP pointed at the fake server."""
    agents = tmp_path / "agents"
    shutil.copytree(ROOT / "agents", agents)
    tool_json = agents / "viernes" / "tool" / "tool.json"
    data = json.loads(tool_json.read_text(encoding="utf-8"))
    data["mcpServers"] = {
        "filesystem": {
            "command": sys.executable,
            "args": ["-m", "tests.fakes.fake_filesystem_server", str(notes_dir)],
        }
    }
    data["confirm"] = ["filesystem.write_file"]
    tool_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return agents


@pytest.fixture
def env() -> dict[str, str]:
    return dict(os.environ)


def load_spec(
    agents_dir: Path, name: str, settings: TonySettings, env: dict[str, str]
) -> AgentSpec:
    return load_agent(agents_dir / name, settings, env)


class TeeSink:
    def __init__(self, *sinks) -> None:
        self.sinks = sinks

    def emit(self, event_type: str, payload: dict) -> None:
        for sink in self.sinks:
            sink.emit(event_type, payload)


async def run_task_eval(
    eval: TaskEval, spec: AgentSpec, settings: TonySettings
) -> tuple[TaskResult, ListEventSink]:
    events = ListEventSink()
    if not LIVE:
        runner = ReplayRunner(FIXTURES_DIR / f"{eval.id}.jsonl")
        return await runner.run(spec, eval.request(), ToolCatalog.empty(), events), events
    log = JsonlEventSink(RUNS_DIR, eval.id, [])
    manager = McpManager(connect_timeout_s=settings.limits.mcp_connect_timeout_s)
    try:
        await manager.start(spec.tools)
        handlers = WorkerToolHandlers(spec, SubagentLauncher(None, eval.id, spec.subagents))
        runner = ClaudeSdkRunner(
            settings=settings,
            task_id=eval.id,
            gate=AutoConfirmGate(eval.confirm),
            call=manager.call,
            native_handlers=handlers,
        )
        result = await runner.run(spec, eval.request(), manager.catalog, TeeSink(log, events))
        log.emit("task.result", {"result": result.model_dump()})
    finally:
        await manager.stop()
        log.close()
    return result, events


async def no_tools(qualified: str, args: dict, timeout: float) -> ToolCallOutcome:
    return ToolCallOutcome.failure(f"el front no tiene la tool {qualified}")


def conversation_parts(
    eval: ConversationEval, worker: AgentSpec, settings: TonySettings, tmp_path: Path
):
    """(front runner, worker factory, clock) for one conversation eval in the current mode."""
    if LIVE:
        factory = SdkWorkerFactory(settings, worker, tmp_path / "logs", [])
        runner = RecordingConversationRunner(
            ClaudeSdkConversation(settings, AutoConfirmGate(True), no_tools), run_path(eval.id)
        )
        return runner, factory, SystemClock()
    runner = ReplayConversationRunner(FIXTURES_DIR / f"{eval.id}.jsonl")
    factory = FakeWorkerFactory(FakeClock())
    for objetivo, result in runner.task_results().items():
        factory.custom_runners[objetivo] = FakeAgentRunner(result)
    return runner, factory, factory.clock


async def judge_one_shot(settings: TonySettings):
    async def ask(prompt: str, schema: dict):
        return await one_shot(settings, JUDGE_MODEL, prompt, schema=schema)

    return ask
