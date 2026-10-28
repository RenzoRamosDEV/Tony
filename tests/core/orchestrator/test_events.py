"""Per-task event bus and the sink the worker writes through."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.fakes.sinks import ListEventSink
from tony.core.logging import JsonlEventSink
from tony.core.orchestrator.events import TaskEventBus, TaskEventSink
from tony.core.orchestrator.task import TASK_PROGRESS, TASK_RESULT, Event


async def collect(bus: TaskEventBus) -> list[Event]:
    return [event async for event in bus.stream()]


def test_sink_writes_every_event_to_the_log_and_the_bus() -> None:
    bus = TaskEventBus("t1")
    log = ListEventSink()
    sink = TaskEventSink(bus, log)

    sink.emit("task.started", {"agent": "v"})

    assert log.events == [("task.started", {"agent": "v"})]
    assert [(e.type, e.payload) for e in bus.history] == [("task.started", {"agent": "v"})]
    assert bus.history[0].task_id == "t1"


def test_each_tool_call_produces_a_progress_event_with_increasing_step() -> None:
    bus = TaskEventBus("t1")
    log = ListEventSink()
    sink = TaskEventSink(bus, log)

    for name in ("fs.a", "fs.b", "fs.c"):
        sink.emit("tool.call", {"tool": name, "args": {}})

    assert log.payloads(TASK_PROGRESS) == [
        {"tool": "fs.a", "step": 1},
        {"tool": "fs.b", "step": 2},
        {"tool": "fs.c", "step": 3},
    ]
    assert [e.type for e in bus.history] == ["tool.call", TASK_PROGRESS] * 3


def test_sink_without_log_only_feeds_the_bus() -> None:
    bus = TaskEventBus("t1")

    TaskEventSink(bus).emit("x", {})

    assert [e.type for e in bus.history] == ["x"]


def test_bus_assigns_increasing_seq_and_timestamps() -> None:
    bus = TaskEventBus("t1", now=lambda: "2026-10-28T10:00:00.000Z")

    first = bus.publish("a", {})
    second = bus.publish("b", {})

    assert (first.seq, second.seq) == (1, 2)
    assert first.ts == "2026-10-28T10:00:00.000Z"


async def test_late_subscriber_replays_history_then_follows_live_events() -> None:
    bus = TaskEventBus("t1")
    bus.publish("task.queued", {})
    bus.publish("task.running", {})

    consumer = asyncio.ensure_future(collect(bus))
    await asyncio.sleep(0)
    bus.publish(TASK_PROGRESS, {"tool": "x", "step": 1})
    bus.publish(TASK_RESULT, {"result": {}})

    events = await asyncio.wait_for(consumer, 1)
    assert [e.type for e in events] == ["task.queued", "task.running", TASK_PROGRESS, TASK_RESULT]


async def test_two_consumers_receive_the_same_event() -> None:
    bus = TaskEventBus("t1")
    first = asyncio.ensure_future(collect(bus))
    second = asyncio.ensure_future(collect(bus))
    await asyncio.sleep(0)

    bus.publish(TASK_PROGRESS, {"tool": "x", "step": 1})
    bus.publish(TASK_RESULT, {"result": {}})

    assert await asyncio.wait_for(first, 1) == await asyncio.wait_for(second, 1)


async def test_stream_of_a_closed_bus_ends_after_history() -> None:
    bus = TaskEventBus("t1")
    bus.publish(TASK_RESULT, {"result": {}})

    events = await asyncio.wait_for(collect(bus), 1)

    assert [e.type for e in events] == [TASK_RESULT]
    assert bus.closed is True


def test_task_result_is_the_last_line_of_the_jsonl(tmp_path: Path) -> None:
    bus = TaskEventBus("t1")
    log = JsonlEventSink(tmp_path, "t1", secrets=[])
    sink = TaskEventSink(bus, log)

    sink.emit("task.queued", {})
    sink.emit("tool.call", {"tool": "fs.a", "args": {}})
    sink.emit(TASK_RESULT, {"result": {"status": "ok"}})
    log.close()

    lines = [json.loads(line) for line in log.path.read_text().splitlines()]
    expected_types = ["task.queued", "tool.call", TASK_PROGRESS, TASK_RESULT]
    assert [line["type"] for line in lines] == expected_types
    assert [line["seq"] for line in lines] == [1, 2, 3, 4]
