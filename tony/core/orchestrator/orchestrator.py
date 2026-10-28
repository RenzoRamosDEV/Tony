"""Task orchestrator: queue, lifecycle, events, confirmations, cancellation and timeout."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from tony.core.config import Limits
from tony.core.logging import new_task_id
from tony.core.mcp import ConfirmRequest
from tony.core.orchestrator.clock import Clock, SystemClock
from tony.core.orchestrator.confirm import (
    ConfirmationRegistry,
    OrchestratorConfirmGate,
    PendingConfirmation,
)
from tony.core.orchestrator.errors import UNKNOWN_TASK, OrchestratorError
from tony.core.orchestrator.events import TaskEventBus, TaskEventSink
from tony.core.orchestrator.ports import TaskLog, WorkerFactory
from tony.core.orchestrator.queue import TaskQueue
from tony.core.orchestrator.state import transition
from tony.core.orchestrator.task import (
    SUBTASK_FINISHED,
    SUBTASK_STARTED,
    TASK_CANCELLED,
    TASK_CONFIRMED,
    TASK_NEEDS_CONFIRMATION,
    TASK_QUEUED,
    TASK_RESULT,
    TASK_RUNNING,
    Event,
    Task,
    TaskStatus,
    status_for_result,
)
from tony.core.runner import TaskRequest, TaskResult
from tony.core.runner.cancel import NOT_CONFIRMED_REASON, USER_REASON, CancelToken
from tony.core.runner.claude_sdk import CLEANUP_BUDGET_S
from tony.core.runner.results import error_result, external_cancelled_result, timeout_result

MAX_QUEUED = 10
TIMEOUT_REASON = "timeout"
SHUTDOWN_REASON = "shutdown"


class _TaskContext:
    def __init__(self, task: Task, log: TaskLog) -> None:
        self.task = task
        self.log = log
        self.bus = TaskEventBus(task.id, task.parent_id)
        self.sink = TaskEventSink(self.bus, log)
        self.token = CancelToken()
        self.runner_task: asyncio.Task[None] | None = None


class Orchestrator:
    def __init__(
        self,
        worker_factory: WorkerFactory,
        limits: Limits,
        clock: Clock | None = None,
        new_id: Callable[[], str] = new_task_id,
        max_queued: int = MAX_QUEUED,
    ) -> None:
        self._factory = worker_factory
        self._limits = limits
        self._clock = clock or SystemClock()
        self._new_id = new_id
        self._queue = TaskQueue(max_queued)
        self._contexts: dict[str, _TaskContext] = {}
        self._confirmations = ConfirmationRegistry()
        self._closing = False
        worker_factory.attach_host(self)

    @property
    def tasks(self) -> dict[str, Task]:
        return {task_id: ctx.task for task_id, ctx in self._contexts.items()}

    def submit(
        self, request: TaskRequest, parent_id: str | None = None, agent: str | None = None
    ) -> Task:
        if parent_id is not None:
            parent = self._contexts.get(parent_id)
            if parent is None or parent.task.final:
                raise OrchestratorError(UNKNOWN_TASK)
        task = Task(
            self._new_id(), request, parent_id, agent=agent, created_at=self._clock.monotonic()
        )
        if parent_id is None:
            self._queue.push(task)
        self._register(task)
        if parent_id is None:
            self._pump()
        else:
            self._start(task)
        return task

    def submit_subtask(self, parent_id: str, agent: str, request: TaskRequest) -> Task:
        return self.submit(request, parent_id, agent)

    def children(self, task_id: str) -> list[Task]:
        return [ctx.task for ctx in self._contexts.values() if ctx.task.parent_id == task_id]

    async def confirm(
        self,
        confirmation_id: str,
        approved: bool,
        tool: str | None = None,
        args: dict[str, Any] | None = None,
    ) -> None:
        self._confirmations.resolve(confirmation_id, approved, tool, args)

    async def cancel(self, task_id: str, reason: str = USER_REASON) -> None:
        ctx = self._context(task_id)
        task = ctx.task
        async with task.lock:
            if task.final:
                return
            was_queued = task.status == TaskStatus.QUEUED
            transition(task, TaskStatus.CANCELLED)
            await self._cascade(task, TaskStatus.CANCELLED, reason)
            self._confirmations.invalidate_owner(task.id)
            ctx.token.cancel(reason)
            ctx.sink.emit(TASK_CANCELLED, {"reason": reason})
        if was_queued:
            self._queue.remove(task.id)
            await self._finish(ctx, None)

    def events(self, task_id: str) -> AsyncIterator[Event]:
        return self._context(task_id).bus.stream()

    async def wait(self, task_id: str) -> TaskResult:
        task = self._context(task_id).task
        await task.finished.wait()
        assert task.result is not None
        return task.result

    async def close(self) -> None:
        self._closing = True
        for task_id, ctx in list(self._contexts.items()):
            if not ctx.task.final:
                await self.cancel(task_id, SHUTDOWN_REASON)
        pending = [ctx.runner_task for ctx in self._contexts.values() if ctx.runner_task]
        await asyncio.gather(*pending, return_exceptions=True)
        await self._factory.close()

    async def request_confirmation(self, task_id: str, request: ConfirmRequest) -> bool:
        ctx = self._context(task_id)
        task = ctx.task
        async with self._confirmations.lock_for(self._root_of(task_id)):
            async with task.lock:
                if task.final:
                    return False
                transition(task, TaskStatus.WAITING_CONFIRMATION)
                pending = self._confirmations.register(task_id, request)
                payload = {
                    "confirmation_id": request.confirmation_id,
                    "tool": request.tool,
                    "args": json.loads(request.args_normalized),
                }
                ctx.sink.emit(TASK_NEEDS_CONFIRMATION, payload)
                if task.parent_id is not None:
                    self._context(task.parent_id).bus.publish(
                        TASK_NEEDS_CONFIRMATION, {**payload, "task_id": task.id}
                    )
            approved = await self._await_answer(pending)
            if pending.invalidated:
                return False
            ctx.sink.emit(
                TASK_CONFIRMED, {"confirmation_id": request.confirmation_id, "approved": approved}
            )
            if approved:
                async with task.lock:
                    transition(task, TaskStatus.RUNNING)
                return True
        await self.cancel(task_id, NOT_CONFIRMED_REASON)
        return False

    async def _await_answer(self, pending: PendingConfirmation) -> bool:
        expiry = asyncio.ensure_future(self._clock.sleep(self._limits.confirm_timeout_s))
        try:
            done, _ = await asyncio.wait(
                {pending.future, expiry}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            expiry.cancel()
        if pending.future in done:
            return pending.future.result()
        self._confirmations.discard(pending.confirmation_id)
        return False

    def _context(self, task_id: str) -> _TaskContext:
        ctx = self._contexts.get(task_id)
        if ctx is None:
            raise OrchestratorError(UNKNOWN_TASK)
        return ctx

    def _root_of(self, task_id: str) -> str:
        task = self._context(task_id).task
        while task.parent_id is not None:
            task = self._context(task.parent_id).task
        return task.id

    def _register(self, task: Task) -> None:
        ctx = _TaskContext(task, self._factory.open_log(task.id, task.parent_id))
        self._contexts[task.id] = ctx
        ctx.sink.emit(TASK_QUEUED, {"objetivo": task.request.objetivo, "parent_id": task.parent_id})

    def _pump(self) -> None:
        if self._closing:
            return
        task = self._queue.start_next()
        if task is not None:
            self._start(task)

    def _start(self, task: Task) -> None:
        ctx = self._contexts[task.id]
        ctx.runner_task = asyncio.get_running_loop().create_task(self._run_task(ctx))

    async def _run_task(self, ctx: _TaskContext) -> None:
        task = ctx.task
        async with task.lock:
            if task.final:
                return
            transition(task, TaskStatus.RUNNING)
            task.started_at = self._clock.monotonic()
            ctx.sink.emit(TASK_RUNNING, {})
        self._emit_to_parent(task, SUBTASK_STARTED, {"task_id": task.id, "agent": task.agent})
        await self._finish(ctx, await self._supervise(ctx))

    async def _supervise(self, ctx: _TaskContext) -> TaskResult | None:
        run = asyncio.ensure_future(self._build_and_run(ctx))
        deadline = asyncio.ensure_future(self._clock.sleep(self._remaining_s(ctx.task)))
        cancelled = asyncio.ensure_future(ctx.token.wait())
        try:
            done, _ = await asyncio.wait(
                {run, deadline, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            deadline.cancel()
            cancelled.cancel()
        if run not in done:
            if deadline in done:
                await self._expire(ctx)
            await self._abandon_after_budget(run)
        return _result_of(run)

    async def _build_and_run(self, ctx: _TaskContext) -> TaskResult:
        task = ctx.task
        worker = await self._factory.build_worker(
            task, ctx.sink, ctx.token, OrchestratorConfirmGate(self, task.id)
        )
        return await worker.runner.run(worker.spec, task.request, worker.catalog, ctx.sink)

    async def _abandon_after_budget(self, run: asyncio.Future[TaskResult]) -> None:
        budget = asyncio.ensure_future(self._clock.sleep(CLEANUP_BUDGET_S))
        try:
            await asyncio.wait({run, budget}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            budget.cancel()
        if not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)

    def _remaining_s(self, task: Task) -> float:
        """A subtask shares its parent's deadline instead of getting a full timeout."""
        timeout = self._limits.task_timeout_s
        if task.parent_id is None:
            return timeout
        parent = self._context(task.parent_id).task
        if parent.started_at is None:
            return timeout
        return max(0.0, parent.started_at + timeout - self._clock.monotonic())

    async def _expire(self, ctx: _TaskContext) -> None:
        task = ctx.task
        async with task.lock:
            if task.final:
                return
            transition(task, TaskStatus.TIMEOUT)
            await self._cascade(task, TaskStatus.TIMEOUT, TIMEOUT_REASON)
            self._confirmations.invalidate_owner(task.id)
            ctx.token.cancel(TIMEOUT_REASON)

    async def _cascade(self, parent: Task, status: TaskStatus, reason: str) -> None:
        """Apply the parent's final transition to every child still in flight."""
        for child in self.children(parent.id):
            ctx = self._context(child.id)
            async with child.lock:
                if child.final:
                    continue
                transition(child, status)
                self._confirmations.invalidate_owner(child.id)
                ctx.token.cancel(reason)
                if status == TaskStatus.CANCELLED:
                    ctx.sink.emit(TASK_CANCELLED, {"reason": reason})

    def _emit_to_parent(self, task: Task, event_type: str, payload: dict[str, Any]) -> None:
        if task.parent_id is not None:
            self._context(task.parent_id).sink.emit(event_type, payload)

    async def _finish(self, ctx: _TaskContext, runner_result: TaskResult | None) -> None:
        task = ctx.task
        async with task.lock:
            if task.final:
                result = self._settled_result(ctx, runner_result)
            else:
                assert runner_result is not None
                result = runner_result
                transition(task, status_for_result(result))
            task.result = result
            task.finished_at = self._clock.monotonic()
            ctx.sink.emit(TASK_RESULT, {"result": result.model_dump()})
        ctx.log.close()
        await self._factory.release(task.id)
        self._emit_to_parent(task, SUBTASK_FINISHED, {"task_id": task.id, "status": task.status})
        task.finished.set()
        self._queue.release(task)
        self._pump()

    def _settled_result(self, ctx: _TaskContext, runner_result: TaskResult | None) -> TaskResult:
        status = ctx.task.status
        if runner_result is not None and runner_result.status == status.value:
            return runner_result
        if status == TaskStatus.TIMEOUT:
            return timeout_result(self._limits.task_timeout_s, [])
        return external_cancelled_result(ctx.token.reason, [])


def _result_of(run: asyncio.Future[TaskResult]) -> TaskResult | None:
    if run.cancelled():
        return None
    exc = run.exception()
    if exc is not None:
        return error_result(str(exc) or exc.__class__.__name__, [])
    result = run.result()
    return result if isinstance(result, TaskResult) else None
