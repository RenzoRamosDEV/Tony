"""WebChannel, TaskStreamer and UsageTracker (design.md D8) over a real ConversationStream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from tests.fakes.clock import FakeClock
from tony.apps.web.confirmations import ConfirmationRouter
from tony.apps.web.protocol import ConversationStream, Envelope
from tony.apps.web.ws_channel import UsageTracker, WebChannel
from tony.core.channels.ports import (
    AssistantDelta,
    AssistantReply,
    AssistantWait,
    NeedsConfirmation,
    Notice,
    TaskEvent,
    TaskProgress,
    UserAccepted,
)
from tony.core.orchestrator.task import Event

TOKEN_ALERT = 50000
BIG_USAGE = {"input_tokens": 41200, "output_tokens": 9900, "total_cost_usd": 0.31}
CHILD_USAGE = {"input_tokens": 20000, "output_tokens": 5000}
ROOT_USAGE = {"input_tokens": 25000, "output_tokens": 5000}


class FakeOrchestrator:
    def __init__(self) -> None:
        self.confirmations: list[tuple[str, bool, str, dict[str, Any]]] = []
        self.scripted: dict[str, list[Event]] = {}
        self.open_streams: dict[str, asyncio.Event] = {}

    async def confirm(self, confirmation_id, approved, tool=None, args=None) -> None:
        self.confirmations.append((confirmation_id, approved, tool, args))

    async def events(self, task_id: str) -> AsyncIterator[Event]:
        for event in self.scripted.get(task_id, []):
            yield event
        if task_id in self.open_streams:
            await self.open_streams[task_id].wait()


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = FakeClock()
        self.stream = ConversationStream("c1")
        self.router = ConfirmationRouter(now=self.clock.monotonic, timeout_s=60)
        self.orchestrator = FakeOrchestrator()
        self.logs = tmp_path / "logs"
        self.channel = WebChannel(
            self.stream,
            self.router,
            self.orchestrator,  # type: ignore[arg-type]
            UsageTracker(TOKEN_ALERT),
            self.logs,
            confirm_timeout_s=60,
        )

    def published(self) -> list[Envelope]:
        return self.stream.replay(0) or []

    def types(self) -> list[str]:
        return [e.type for e in self.published()]


def event(
    task_id: str, type_: str, payload: dict[str, Any], seq: int = 1, parent_id: str | None = None
) -> TaskEvent:
    return TaskEvent(task_id, parent_id, type_, payload, seq, "2026-10-28T09:00:00.000Z")


def bus_event(task_id: str, type_: str, payload: dict, parent_id: str | None = None) -> Event:
    return Event(task_id, type_, payload, 1, "2026-10-28T09:00:00.000Z", parent_id)


async def test_user_accepted_delta_and_wait_become_envelopes(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(UserAccepted("u1", "text"))
    await h.channel.send(AssistantDelta("a1", "Hola"))
    await h.channel.send(AssistantWait("Dame un momento."))
    await h.channel.send(TaskProgress("t-9", "fs.read", 1))

    accepted, delta, wait = h.published()
    assert (accepted.type, accepted.message_id, accepted.payload) == (
        "user.accepted",
        "u1",
        {"message_id": "u1", "effective_mode": "text"},
    )
    assert (delta.type, delta.message_id, delta.payload) == (
        "assistant.delta",
        "a1",
        {"text": "Hola"},
    )
    assert (wait.type, wait.payload) == ("assistant.wait", {"text": "Dame un momento."})


async def test_reply_publishes_front_usage_then_final(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    usage = {"input_tokens": 1200, "output_tokens": 80, "total_cost_usd": 0.02, "num_turns": 1}

    await h.channel.send(AssistantReply("Hola, Renzo.", None, "text", "a1", usage))

    usage_env, final = h.published()
    assert usage_env.type == "usage" and usage_env.task_id is None
    assert usage_env.payload == {
        "task_id": None,
        "input_tokens": 1200,
        "output_tokens": 80,
        "cost_usd": 0.02,
        "cumulative_tokens": 1280,
        "alert": False,
    }
    assert (final.type, final.message_id) == ("assistant.final", "a1")
    assert final.payload == {
        "display_text": "Hola, Renzo.",
        "speech_text": None,
        "message_id": "a1",
    }


async def test_front_usage_counts_each_turn_on_its_own(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    big = {"input_tokens": 30000, "output_tokens": 0}

    await h.channel.send(AssistantReply("a", None, "text", "a1", big))
    await h.channel.send(AssistantReply("b", None, "text", "a2", big))

    second = h.published()[2].payload
    assert second["cumulative_tokens"] == 30000 and second["alert"] is False


async def test_reply_without_usage_reports_zeros(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(AssistantReply("Hola.", "Hola.", "voice", "a1"))

    usage_env = h.published()[0]
    assert usage_env.payload == {
        "task_id": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "cumulative_tokens": 0,
        "alert": False,
    }


async def test_failed_turn_publishes_turn_failed_before_final(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(AssistantReply("No pude.", None, "text", "a1", {}, error="boom"))

    assert h.types() == ["error", "usage", "assistant.final"]
    assert h.published()[0].payload == {"code": "turn_failed", "detail": "boom"}


async def test_notice_is_an_error_envelope_with_code_notice(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(Notice("Configuración recargada"))

    assert h.published()[0].type == "error"
    assert h.published()[0].payload == {"code": "notice", "detail": "Configuración recargada"}


async def test_needs_confirmation_registers_in_the_router_and_publishes(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    args = {"source": "/n/a", "destination": "/n/b"}

    await h.channel.send(NeedsConfirmation("t-9", "a3f", "filesystem.move_file", args))

    env = h.published()[0]
    assert (env.type, env.task_id) == ("task.needs_confirmation", "t-9")
    assert env.payload == {
        "confirmation_id": "a3f",
        "tool": "filesystem.move_file",
        "args": args,
        "expires_in_s": 60,
    }
    view = h.router.pending()
    assert view is not None and view.task_id == "t-9"
    await h.router.resolve("a3f", True)
    assert h.orchestrator.confirmations == [("a3f", True, "filesystem.move_file", args)]


async def test_task_queued_carries_the_log_path_when_the_file_exists(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    log = h.logs / "20261028" / "t-9.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("", encoding="utf-8")

    await h.channel.send(event("t-9", "task.queued", {"objetivo": "x", "parent_id": None}))
    await h.channel.send(event("t-8", "task.queued", {"objetivo": "y", "parent_id": None}))

    first, second = h.published()
    assert first.task_id == "t-9" and first.payload["log_path"] == str(log)
    assert first.payload["objetivo"] == "x"
    assert second.payload["log_path"] is None


async def test_every_task_event_is_published_with_its_task_id_and_payload(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(event("t-9", "task.running", {}))
    await h.channel.send(event("t-9", "tool.call", {"tool": "fs.read", "args": {"k": "***"}}))
    await h.channel.send(event("t-9", "task.progress", {"tool": "fs.read", "step": 1}))
    await h.channel.send(event("t-9", "task.needs_confirmation", {"confirmation_id": "x"}))
    await h.channel.send(event("t-9", "task.result", {"status": "ok", "resumen": "r"}))

    assert h.types() == ["task.running", "tool.call", "task.progress", "task.result"]
    assert all(e.task_id == "t-9" for e in h.published())
    assert h.published()[1].payload == {"tool": "fs.read", "args": {"k": "***"}}
    assert "parent_id" not in h.published()[1].payload


async def test_task_finished_publishes_usage_with_cumulative_tokens_and_alert(tmp_path) -> None:
    h = Harness(tmp_path)
    await h.channel.send(event("t-9", "task.queued", {"objetivo": "x"}))

    await h.channel.send(
        event(
            "t-9",
            "task.finished",
            {
                "status": "ok",
                "usage": {"input_tokens": 41200, "output_tokens": 9900, "total_cost_usd": 0.31},
            },
        )
    )

    finished, usage = h.published()[1:]
    assert finished.type == "task.finished"
    assert (usage.type, usage.task_id) == ("usage", "t-9")
    assert usage.payload == {
        "input_tokens": 41200,
        "output_tokens": 9900,
        "cost_usd": 0.31,
        "cumulative_tokens": 51100,
        "alert": True,
    }


async def test_subtask_events_are_forwarded_with_parent_id_until_the_root_result(tmp_path) -> None:
    h = Harness(tmp_path)
    h.orchestrator.scripted["s-1"] = [
        bus_event("s-1", "task.queued", {"objetivo": "hijo", "parent_id": "t-9"}, "t-9"),
        bus_event("s-1", "tool.call", {"tool": "fs.read", "args": {}}, "t-9"),
        bus_event("s-1", "task.needs_confirmation", {"confirmation_id": "c"}, "t-9"),
        bus_event(
            "s-1",
            "task.finished",
            {"status": "ok", "usage": {"input_tokens": 20000, "output_tokens": 5000}},
            "t-9",
        ),
        bus_event("s-1", "task.result", {"status": "ok"}, "t-9"),
    ]
    h.orchestrator.open_streams["s-2"] = asyncio.Event()
    h.orchestrator.scripted["s-2"] = [bus_event("s-2", "task.queued", {"objetivo": "lento"}, "t-9")]
    await h.channel.send(event("t-9", "task.queued", {"objetivo": "padre"}))
    await h.channel.send(event("t-9", "task.running", {}))

    started = {"task_id": "s-1", "agent": "investigador"}
    await h.channel.send(event("t-9", "subtask.started", started))
    await h.channel.send(event("t-9", "subtask.started", {"task_id": "s-2", "agent": "i"}))
    await h.clock.settle()
    await h.channel.send(event("t-9", "subtask.finished", {"task_id": "s-1", "status": "done"}))
    await h.channel.send(event("t-9", "task.finished", {"status": "ok", "usage": ROOT_USAGE}))
    await h.channel.send(event("t-9", "task.result", {"status": "ok"}))
    await h.clock.settle()

    by_type: dict[tuple[str, str | None], Envelope] = {}
    for e in h.published():
        by_type.setdefault((e.type, e.task_id), e)
    child_call = by_type[("tool.call", "s-1")]
    assert child_call.payload == {"tool": "fs.read", "args": {}, "parent_id": "t-9"}
    assert ("task.needs_confirmation", "s-1") not in by_type
    assert by_type[("subtask.started", "t-9")].payload == started
    child_usage = by_type[("usage", "s-1")].payload
    assert (child_usage["cumulative_tokens"], child_usage["alert"]) == (25000, False)
    root_usage = by_type[("usage", "t-9")].payload
    assert (root_usage["cumulative_tokens"], root_usage["alert"]) == (55000, True)
    assert root_usage["cost_usd"] == 0.0
    assert h.channel.streamer.active_subscriptions == 0


async def test_detached_consumer_is_cancelled_on_close(tmp_path) -> None:
    h = Harness(tmp_path)
    h.orchestrator.open_streams["s-2"] = asyncio.Event()
    await h.channel.send(event("t-9", "task.queued", {"objetivo": "padre"}))
    await h.channel.send(event("t-9", "subtask.started", {"task_id": "s-2", "agent": "i"}))
    await h.clock.settle()
    assert h.channel.streamer.active_subscriptions == 1

    await h.channel.close()

    assert h.channel.streamer.active_subscriptions == 0


async def test_task_end_events_discard_the_pending_confirmation(tmp_path) -> None:
    h = Harness(tmp_path)
    await h.channel.send(NeedsConfirmation("t-9", "a3f", "fs.write", {}))
    assert h.router.pending() is not None

    await h.channel.send(event("t-9", "task.cancelled", {"reason": "not_confirmed"}))

    assert h.router.pending() is None


async def test_config_events_are_published_without_task_id(tmp_path) -> None:
    h = Harness(tmp_path)

    await h.channel.send(
        event("config", "config.reloaded", {"agent": "viernes", "servers": ["fs"]}, 0)
    )
    await h.channel.send(
        event("config", "config.reload_failed", {"agent": "viernes", "error": "x"}, 0)
    )

    reloaded, failed = h.published()
    assert (reloaded.type, reloaded.task_id) == ("config.reloaded", None)
    assert reloaded.payload == {"agent": "viernes", "servers": ["fs"]}
    assert (failed.type, failed.payload) == (
        "config.reload_failed",
        {"agent": "viernes", "error": "x"},
    )


def test_usage_tracker_accumulates_per_root_and_flags_the_alert() -> None:
    tracker = UsageTracker(TOKEN_ALERT)

    child = tracker.record("s-1", "t-9", {"input_tokens": 20000, "output_tokens": 5000})
    root = tracker.record(
        "t-9", "t-9", {"input_tokens": 25000, "output_tokens": 5000, "total_cost_usd": 0.31}
    )
    other = tracker.record("t-10", "t-10", {"input_tokens": 50000, "output_tokens": 0})
    beyond = tracker.record("t-11", "t-11", {"input_tokens": 50000, "output_tokens": 1})

    assert child == {
        "input_tokens": 20000,
        "output_tokens": 5000,
        "cost_usd": 0.0,
        "cumulative_tokens": 25000,
        "alert": False,
    }
    assert root["cumulative_tokens"] == 55000 and root["alert"] is True and root["cost_usd"] == 0.31
    assert other["alert"] is False and beyond["alert"] is True
    assert tracker.record("t-12", "t-12", {}) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "cumulative_tokens": 0,
        "alert": False,
    }


async def test_each_root_task_accumulates_on_its_own(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    for task_id in ("t-1", "t-2"):
        await h.channel.send(event(task_id, "task.queued", {"objetivo": task_id}))
        await h.channel.send(event(task_id, "task.finished", {"status": "ok", "usage": ROOT_USAGE}))
        await h.channel.send(event(task_id, "task.result", {"status": "ok"}))

    usages = [e.payload for e in h.published() if e.type == "usage"]

    assert [u["cumulative_tokens"] for u in usages] == [30000, 30000]
