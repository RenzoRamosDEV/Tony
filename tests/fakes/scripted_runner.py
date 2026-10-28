"""AgentRunner double that follows a script of steps, honouring the cancel token.

Steps: ("tool", name, args), ("confirm", name, args), ("sleep", seconds),
("raise", message), ("result", TaskResult).
"""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fakes.clock import FakeClock
from tony.core.loader import AgentSpec
from tony.core.mcp import ConfirmGate, ConfirmRequest, ToolCallOutcome, ToolCatalog
from tony.core.runner import EventSink, TaskRequest, TaskResult
from tony.core.runner.cancel import CancelToken
from tony.core.runner.proxy import NOT_CONFIRMED, TaskState, ToolCaller
from tony.core.runner.results import cancelled_result

Step = tuple[Any, ...]
DEFAULT_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_cost_usd": 0.01, "num_turns": 2}


async def _ok_call(qualified: str, args: dict[str, Any], timeout: float) -> ToolCallOutcome:
    return ToolCallOutcome(ok=True, content="", duration_ms=1)


class ScriptedRunner:
    def __init__(
        self,
        task_id: str,
        script: list[Step],
        cancel_token: CancelToken | None = None,
        clock: FakeClock | None = None,
        call: ToolCaller | None = None,
        gate: ConfirmGate | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = task_id
        self.script = list(script)
        self.cancel_token = cancel_token or CancelToken()
        self.clock = clock or FakeClock()
        self.call: ToolCaller = call or _ok_call
        self.gate = gate
        self.usage = usage if usage is not None else DEFAULT_USAGE
        self.state = TaskState(task_id, cancel_token=self.cancel_token)
        self.interrupted_by: str | None = None
        self.calls: list[tuple[AgentSpec, TaskRequest, ToolCatalog]] = []

    async def run(
        self, spec: AgentSpec, request: TaskRequest, tools: ToolCatalog, events: EventSink
    ) -> TaskResult:
        self.calls.append((spec, request, tools))
        events.emit("task.started", {"agent": spec.name, "objetivo": request.objetivo})
        result = await self._follow_script(events)
        events.emit("task.finished", {"status": result.status, "usage": self.usage})
        return result

    async def _follow_script(self, events: EventSink) -> TaskResult:
        for step in self.script:
            if self.cancel_token.cancelled:
                return cancelled_result(self.state)
            kind = step[0]
            if kind == "tool":
                events.emit("tool.call", {"tool": step[1], "args": step[2]})
                await self._execute(step[1], step[2], events)
            elif kind == "confirm":
                if not await self._confirm(step[1], step[2], events):
                    return cancelled_result(self.state)
                await self._execute(step[1], step[2], events)
            elif kind == "sleep":
                await self._sleep(step[1])
            elif kind == "raise":
                raise RuntimeError(step[1])
            elif kind == "result":
                return step[1]
            else:
                raise ValueError(f"unknown step {kind}")
        if self.cancel_token.cancelled:
            return cancelled_result(self.state)
        return TaskResult(status="ok", resumen="guion completado", pasos=list(self.state.steps))

    async def _execute(self, name: str, args: dict[str, Any], events: EventSink) -> None:
        outcome = await self.call(name, args, 20)
        events.emit(
            "tool.result",
            {"tool": name, "ok": outcome.ok, "duration_ms": outcome.duration_ms, "error": None},
        )
        self.state.steps.append(f"{name}({', '.join(str(v) for v in args.values())})")

    async def _confirm(self, name: str, args: dict[str, Any], events: EventSink) -> bool:
        events.emit("tool.call", {"tool": name, "args": args})
        assert self.gate is not None, "a confirm step needs a gate"
        approved = await self.gate.confirm(ConfirmRequest.create(self.task_id, name, args))
        if not approved:
            self.state.cancel(name)
            events.emit(
                "tool.result",
                {
                    "tool": name,
                    "ok": False,
                    "duration_ms": 0,
                    "error": NOT_CONFIRMED.format(tool=name),
                },
            )
        return approved

    async def _sleep(self, seconds: float) -> None:
        sleeping = asyncio.ensure_future(self.clock.sleep(seconds))
        cancelled = asyncio.ensure_future(self.cancel_token.wait())
        done, _ = await asyncio.wait({sleeping, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        for future in (sleeping, cancelled):
            future.cancel()
        if cancelled in done:
            self.interrupted_by = self.cancel_token.reason
