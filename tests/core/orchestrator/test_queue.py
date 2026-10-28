"""Root-task queue: FIFO, one active root, bounded size."""

from __future__ import annotations

import pytest

from tony.core.orchestrator.errors import OrchestratorError
from tony.core.orchestrator.queue import TaskQueue
from tony.core.orchestrator.task import Task
from tony.core.runner import TaskRequest


def task(task_id: str, parent_id: str | None = None) -> Task:
    return Task(id=task_id, request=TaskRequest(objetivo=task_id), parent_id=parent_id)


def test_tasks_start_in_fifo_order_one_root_at_a_time() -> None:
    queue = TaskQueue(max_queued=10)
    t1, t2, t3 = task("t1"), task("t2"), task("t3")
    for t in (t1, t2, t3):
        queue.push(t)

    assert queue.start_next() is t1
    assert queue.active is t1
    assert queue.start_next() is None

    queue.release(t1)
    assert queue.active is None
    assert queue.start_next() is t2
    queue.release(t2)
    assert queue.start_next() is t3


def test_eleventh_queued_task_is_rejected_without_changing_the_queue() -> None:
    queue = TaskQueue(max_queued=10)
    queue.push(task("active"))
    queue.start_next()
    for i in range(10):
        queue.push(task(f"q{i}"))

    with pytest.raises(OrchestratorError) as excinfo:
        queue.push(task("q10"))

    assert excinfo.value.code == "queue_full"
    assert len(queue) == 10


def test_boundary_tenth_task_is_accepted() -> None:
    queue = TaskQueue(max_queued=10)
    for i in range(9):
        queue.push(task(f"q{i}"))

    queue.push(task("q9"))

    assert len(queue) == 10


def test_removing_a_queued_task_skips_it() -> None:
    queue = TaskQueue(max_queued=10)
    queue.push(task("t1"))
    queue.push(task("t2"))

    assert queue.remove("t1") is True
    assert queue.remove("missing") is False
    assert [t.id for t in queue.queued] == ["t2"]
    assert queue.start_next().id == "t2"


def test_releasing_a_task_that_is_not_active_is_a_no_op() -> None:
    queue = TaskQueue(max_queued=10)
    queue.push(task("t1"))
    active = queue.start_next()

    queue.release(task("other"))

    assert queue.active is active


def test_empty_queue_starts_nothing() -> None:
    queue = TaskQueue(max_queued=10)

    assert queue.start_next() is None
    assert len(queue) == 0
