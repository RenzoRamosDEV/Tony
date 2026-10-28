"""The test doubles satisfy the core ports."""

from __future__ import annotations

from pathlib import Path

from tests.fakes.fake_runner import FakeAgentRunner
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmRequest, ToolCatalog
from tony.core.runner import AgentRunner, EventSink, TaskRequest, TaskResult


def test_doubles_are_instances_of_the_ports() -> None:
    assert isinstance(ListEventSink(), EventSink)
    assert isinstance(FakeAgentRunner(TaskResult(status="ok", resumen="r")), AgentRunner)


async def test_fake_runner_emits_started_scripted_and_finished() -> None:
    runner = FakeAgentRunner(
        TaskResult(status="ok", resumen="r"), events=[("tool.call", {"tool": "x"})]
    )
    sink = ListEventSink()
    spec = AgentSpec(name="v", role="worker", model="claude-sonnet", path=Path("/tmp/v"))

    result = await runner.run(spec, TaskRequest(objetivo="o"), ToolCatalog.empty(), sink)

    assert result.status == "ok"
    assert sink.types() == ["task.started", "tool.call", "task.finished"]
    assert sink.payloads("task.finished")[0]["status"] == "ok"


async def test_auto_confirm_gate_records_and_answers() -> None:
    gate = AutoConfirmGate(False)
    request = ConfirmRequest.create("t", "fs.write_file", {})

    assert await gate.confirm(request) is False
    assert gate.requests == [request]
