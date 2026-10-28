"""run_subagent handler: unknown names, no host, concurrency limit (specs/subagents)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from tests.fakes.clock import FakeClock
from tony.core.loader import AgentSpec
from tony.core.runner import TaskRequest, TaskResult
from tony.core.subagents.launcher import MAX_CONCURRENT, NO_HOST_ERROR, SubagentLauncher

CHILD = AgentSpec(name="investigador", role="worker", model="claude-sonnet", path=Path("/i"))
OK = TaskResult(status="ok", resumen="hecho")


@dataclass
class Submitted:
    id: str
    agent: str
    request: TaskRequest


class FakeHost:
    def __init__(self, clock: FakeClock, duration_s: float = 0) -> None:
        self.clock = clock
        self.duration_s = duration_s
        self.submitted: list[Submitted] = []
        self.waited: list[str] = []

    def submit_subtask(self, parent_id: str, agent: str, request: TaskRequest) -> Submitted:
        task = Submitted(f"s{len(self.submitted) + 1}", agent, request)
        self.submitted.append(task)
        return task

    async def wait(self, task_id: str) -> TaskResult:
        self.waited.append(task_id)
        await self.clock.sleep(self.duration_s)
        return OK


async def test_unknown_subagent_is_an_error_result_listing_the_available_ones() -> None:
    host = FakeHost(FakeClock())
    launcher = SubagentLauncher(host, "t1", {"investigador": CHILD})

    result = await launcher.run_subagent("nadie", TaskRequest(objetivo="x"))

    assert result.status == "error"
    assert any("nadie" in e and "investigador" in e for e in result.errores)
    assert host.submitted == []


async def test_without_host_run_subagent_explains_where_it_works() -> None:
    launcher = SubagentLauncher(None, "t1", {"investigador": CHILD})

    result = await launcher.run_subagent("investigador", TaskRequest(objetivo="y"))

    assert result.status == "error"
    assert result.errores == [NO_HOST_ERROR]
    assert "tony chat" in NO_HOST_ERROR and "servidor web" in NO_HOST_ERROR


async def test_subtask_is_submitted_with_the_request_and_its_result_returned() -> None:
    host = FakeHost(FakeClock())
    launcher = SubagentLauncher(host, "t1", {"investigador": CHILD})
    request = TaskRequest(objetivo="busca fuentes sobre X")

    result = await launcher.run_subagent("investigador", request)

    assert result == OK
    assert [(s.agent, s.request) for s in host.submitted] == [("investigador", request)]
    assert host.waited == ["s1"]


async def test_the_third_concurrent_subagent_waits_for_a_free_slot() -> None:
    clock = FakeClock()
    host = FakeHost(clock, duration_s=5)
    launcher = SubagentLauncher(host, "t1", {"investigador": CHILD})
    calls = [
        asyncio.ensure_future(launcher.run_subagent("investigador", TaskRequest(objetivo=str(i))))
        for i in range(3)
    ]
    await clock.settle()

    assert MAX_CONCURRENT == 2
    assert len(host.submitted) == 2

    await clock.advance(5)
    assert len(host.submitted) == 3
    assert calls[0].done() and calls[1].done() and not calls[2].done()

    await clock.advance(5)
    assert all(c.done() for c in calls)


async def test_run_subagent_has_no_tool_timeout_of_its_own() -> None:
    clock = FakeClock()
    host = FakeHost(clock, duration_s=2)
    launcher = SubagentLauncher(host, "t1", {"investigador": CHILD}, tool_timeout_s=1)
    call = asyncio.ensure_future(launcher.run_subagent("investigador", TaskRequest(objetivo="o")))
    await clock.advance(1)
    assert not call.done()

    await clock.advance(1)

    assert (await call).status == "ok"


async def test_unknown_subagent_messages_are_exact() -> None:
    with_children = SubagentLauncher(
        FakeHost(FakeClock()), "t1", {"investigador": CHILD, "a": CHILD}
    )
    without = SubagentLauncher(FakeHost(FakeClock()), "t1", {})

    first = await with_children.run_subagent("nadie", TaskRequest(objetivo="x"))
    second = await without.run_subagent("nadie", TaskRequest(objetivo="x"))

    assert first.errores == ["subagente 'nadie' desconocido; disponibles: a, investigador"]
    assert first.resumen == (
        "No se pudo ejecutar el subagente: subagente 'nadie' desconocido; "
        "disponibles: a, investigador"
    )
    assert second.errores == ["subagente 'nadie' desconocido; disponibles: ninguno"]
