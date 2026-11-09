import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from tony.core.config.placeholders import SecretMasker
from tony.core.events import core_events, log_events
from tony.core.events.core_events import Publisher
from tony.core.events.messages import Ruling, ToolCall
from tony.core.evidence.observed import ObservedTexts
from tony.core.guard.audit import args_hash, args_preview
from tony.core.guard.port import Guard
from tony.core.logging.task_log import Clock, utc_now
from tony.core.mcp.manager import CatalogTool
from tony.core.memory.actions import ActionState
from tony.core.orchestrator.ports import (
    ActionRecorder,
    ActionSnapshots,
    EventSink,
    ProxiedTool,
    ToolReply,
)
from tony.core.orchestrator.supervisor import TaskSupervisor

UNTIMED_TOOLS = frozenset({"tony.run_subagent", "tony.ask_user"})
"""Bounded by the parent task's timeout and cancellation (or their own wait) instead of the
per-call timeout."""

NATIVE_PREFIX = "tony."


JOURNAL_SOURCE = "journal"
UNDO_SOURCE = "undo"


@dataclass(frozen=True)
class _Execution:
    reply: ToolReply
    state: ActionState
    detail: str = ""


class ToolCaller(Protocol):
    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply: ...


class ToolProxy:
    """The single path every agent tool call takes: log, guard, execute, mask, log."""

    def __init__(
        self,
        *,
        task_id: str,
        agent: str,
        guard: Guard,
        caller: ToolCaller,
        sink: EventSink,
        masker: SecretMasker,
        supervisor: TaskSupervisor,
        publish: Publisher = core_events.no_op,
        clock: Clock = utc_now,
        journal: ActionRecorder | None = None,
        snapshots: ActionSnapshots | None = None,
        observed: ObservedTexts | None = None,
    ) -> None:
        self._observed = observed
        self._journal = journal
        self._journal_failure_reported = False
        self._snapshots = snapshots
        self._snapshot_failure_reported = False
        self._task_id = task_id
        self._agent = agent
        self._guard = guard
        self._caller = caller
        self._sink = sink
        self._masker = masker
        self._supervisor = supervisor
        self._publish = publish
        self._clock = clock

    def wrap(self, catalog: list[CatalogTool]) -> list[ProxiedTool]:
        return [
            ProxiedTool(
                id=tool.id,
                description=tool.description,
                input_schema=tool.input_schema,
                handler=self._handler_for(tool.id),
            )
            for tool in catalog
        ]

    async def call(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        self._sink.emit(log_events.tool_call(self._agent, tool_id, args))
        reply = await self._judge_and_execute(tool_id, args)
        reply = ToolReply(text=self._masker.mask(reply.text), is_error=reply.is_error)
        self._sink.emit(
            log_events.tool_result(self._agent, tool_id, ok=not reply.is_error, content=reply.text)
        )
        if reply.is_error:
            return reply
        limit = self._supervisor.limits.tool_result_max_chars
        capped = ToolReply(text=cap_text(reply.text, limit))
        self._observe(tool_id, capped)
        return capped

    def _observe(self, tool_id: str, reply: ToolReply) -> None:
        # Native results (skill bodies, user answers, model-written subagent results) are not
        # evidence: recording them would let the model launder its own text into sources.
        if self._observed is not None and not tool_id.startswith(NATIVE_PREFIX):
            self._observed.add(reply.text)

    async def _judge_and_execute(self, tool_id: str, args: dict[str, Any]) -> ToolReply:
        if not self._supervisor.step(self._agent):
            return _not_executed(tool_id, self._supervisor.reason)
        digest = args_hash(args)
        envelope = ToolCall(task_id=self._task_id, agent=self._agent, tool=tool_id, args=args)
        ruling = await self._guard.decide(envelope)
        preview = args_preview(args, self._masker)
        self._publish(
            core_events.tool_call(
                self._task_id, self._agent, tool_id, preview, ruling, clock=self._clock
            )
        )
        if ruling.verdict == "deny":
            self._supervisor.denied(tool_id, ruling.rule)
            return _blocked(ruling)
        if ruling.verdict == "confirm" and ruling.user_decision != "allow":
            self._supervisor.unconfirmed(tool_id, ruling.rule, ruling.user_decision)
            decision = ruling.user_decision or "deny"
            return _not_executed(tool_id, f"not confirmed by the user ({decision})")
        if args_hash(args) != digest:
            self._supervisor.unconfirmed(tool_id, ruling.rule, "deny")
            return _not_executed(tool_id, "not confirmed by the user (arguments changed)")
        call_id = self._record(
            lambda journal: journal.prepared(self._task_id, self._agent, tool_id, digest)
        )
        self._snapshot_before_write(call_id, tool_id, args)
        self._transition(call_id, "dispatched")
        execution = await self._execute(tool_id, args)
        detail = execution.detail or self._written_digest(execution, tool_id, args)
        self._transition(call_id, execution.state, detail)
        return execution.reply

    def _snapshot_before_write(self, call_id: str | None, tool_id: str, args: dict[str, Any]):
        if call_id is not None and self._snapshots is not None:
            self._best_effort_undo(lambda snapshots: snapshots.keep(call_id, tool_id, args))

    def _written_digest(self, execution: _Execution, tool_id: str, args: dict[str, Any]) -> str:
        if execution.state != "succeeded" or self._snapshots is None:
            return ""
        return (
            self._best_effort_undo(lambda snapshots: snapshots.written_digest(tool_id, args)) or ""
        )

    def _best_effort_undo(self, work):
        """Undo bookkeeping never gates a call: a failure is reported once and ignored."""
        try:
            return work(self._snapshots)
        except Exception as error:
            if not self._snapshot_failure_reported:
                self._snapshot_failure_reported = True
                message = f"undo snapshot failed: {error}"
                self._publish(core_events.error(UNDO_SOURCE, message, clock=self._clock))
            return None

    async def _execute(self, tool_id: str, args: dict[str, Any]) -> _Execution:
        timeout = None if tool_id in UNTIMED_TOOLS else self._supervisor.limits.tool_timeout_s
        try:
            reply = await asyncio.wait_for(self._caller.call(tool_id, args), timeout)
        except TimeoutError:
            text = f"tool {tool_id} timed out after {timeout:g} s"
            return _Execution(
                ToolReply(text=text, is_error=True),
                "outcome_unknown",
                f"timed out after {timeout:g} s",
            )
        except Exception as error:
            text = f"tool {tool_id} failed: {error}"
            return _Execution(ToolReply(text=text, is_error=True), "failed", str(error))
        if reply.is_error:
            return _Execution(reply, "failed", reply.text)
        return _Execution(reply, "succeeded")

    def _transition(self, call_id: str | None, state: ActionState, detail: str = "") -> None:
        if call_id is not None:
            self._record(lambda journal: journal.transition(call_id, state, detail))

    def _record(self, write):
        """Journal writes are evidence, not a gate: a failure is reported once and ignored."""
        if self._journal is None:
            return None
        try:
            return write(self._journal)
        except Exception as error:
            if not self._journal_failure_reported:
                self._journal_failure_reported = True
                message = f"action journal write failed: {error}"
                self._publish(core_events.error(JOURNAL_SOURCE, message, clock=self._clock))
            return None

    def _handler_for(self, tool_id: str):
        async def handler(args: dict[str, Any]) -> ToolReply:
            return await self.call(tool_id, args)

        return handler


def cap_text(text: str, limit: int) -> str:
    """Cut text to `limit` characters plus a marker with both sizes; 0 disables the cap."""
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}\n[truncated: showing first {limit} of {len(text)} characters]"


def _blocked(ruling: Ruling) -> ToolReply:
    text = json.dumps({"error": "blocked_by_policy", "rule": ruling.rule})
    return ToolReply(text=text, is_error=True)


def _not_executed(tool_id: str, why: str) -> ToolReply:
    return ToolReply(text=f"tool {tool_id} was not executed: {why}", is_error=True)
