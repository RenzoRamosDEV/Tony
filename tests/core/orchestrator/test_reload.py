"""AgentReloader: validate, swap the MCP generation, keep the last valid config."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.apps.cli_helpers import FakeManager, write_agent
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.loader import load_agent
from tony.core.orchestrator.reload import CONFIG_RELOAD_FAILED, CONFIG_RELOADED, AgentReloader
from tony.core.orchestrator.task import Task
from tony.core.orchestrator.worker import SdkWorkerFactory
from tony.core.runner import TaskRequest
from tony.core.runner.cancel import CancelToken

FAKE = {"command": "python", "args": ["-m", "tests.fakes.fake_mcp_server"]}


class Harness:
    def __init__(self, tmp_repo: Path) -> None:
        self.agents = tmp_repo / "agents"
        write_agent(self.agents, "viernes", "worker")
        write_agent(self.agents, "jarvis", "front", model="claude-haiku")
        self.write_tool_json({"mcpServers": {"fake": FAKE}})
        self.settings = load_settings(None)
        self.env = {"HOME": "/home/x"}
        self.managers: list[FakeManager] = []
        self.events = ListEventSink()
        self.notices: list[str] = []
        self.factory = SdkWorkerFactory(
            self.settings,
            load_agent(self.agents / "viernes", self.settings, self.env),
            tmp_repo / "logs",
            [],
            manager_factory=self.manager_factory,
            runner_factory=lambda *args: object(),
        )
        self.reloader = AgentReloader(
            self.agents, self.settings, self.env, self.factory, self.events, self.notify
        )

    def manager_factory(self, settings) -> FakeManager:
        manager = FakeManager()
        self.managers.append(manager)
        return manager

    async def notify(self, text: str) -> None:
        self.notices.append(text)

    def write_tool_json(self, data: dict | str) -> None:
        tool = self.agents / "viernes" / "tool"
        tool.mkdir(exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        (tool / "tool.json").write_text(text, encoding="utf-8")

    async def build(self, task_id: str):
        task = Task(task_id, TaskRequest(objetivo=task_id))
        return await self.factory.build_worker(
            task, ListEventSink(), CancelToken(), AutoConfirmGate(True)
        )


@pytest.fixture
def h(tmp_repo: Path) -> Harness:
    return Harness(tmp_repo)


async def test_invalid_json_keeps_the_current_generation(h: Harness) -> None:
    await h.build("t1")
    current = h.factory.pool.current
    h.write_tool_json("{not json")

    await h.reloader.reload("viernes")

    failed = h.events.payloads(CONFIG_RELOAD_FAILED)
    assert len(failed) == 1 and failed[0]["agent"] == "viernes"
    assert "tool.json" in failed[0]["error"]
    assert h.events.payloads(CONFIG_RELOADED) == []
    assert h.factory.pool.current is current and len(h.managers) == 1
    assert any("viernes" in n and "tool.json" in n for n in h.notices)
    worker = await h.build("t2")
    assert worker.catalog is h.managers[0].catalog
    await h.factory.close()


async def test_undefined_variable_is_reported_by_name(h: Harness) -> None:
    h.write_tool_json({"mcpServers": {"fake": {**FAKE, "args": ["${NO_EXISTE}"]}}})

    await h.reloader.reload("viernes")

    failed = h.events.payloads(CONFIG_RELOAD_FAILED)
    assert len(failed) == 1 and "NO_EXISTE" in failed[0]["error"]
    assert h.managers == []


async def test_valid_reload_swaps_generations_for_new_tasks_only(h: Harness) -> None:
    first = await h.build("t1")
    h.write_tool_json({"mcpServers": {"fake": FAKE, "fake2": FAKE}})

    await h.reloader.reload("viernes")

    assert h.events.payloads(CONFIG_RELOADED) == [
        {"agent": "viernes", "servers": ["fake", "fake2"]}
    ]
    assert h.events.payloads(CONFIG_RELOAD_FAILED) == []
    assert set(h.managers[1].started_with.mcpServers) == {"fake", "fake2"}
    assert h.managers[0].stopped is False
    second = await h.build("t2")
    assert second.catalog is h.managers[1].catalog
    assert first.catalog is h.managers[0].catalog
    assert any("viernes" in n and "fake2" in n for n in h.notices)
    await h.factory.release("t1")
    assert h.managers[0].stopped is True
    await h.factory.close()


async def test_reload_updates_skills_and_subagents_of_the_worker(h: Harness) -> None:
    skill = h.agents / "viernes" / "skills" / "nueva" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: nueva\ndescription: d\n---\ncuerpo\n", encoding="utf-8")
    write_agent(h.agents / "viernes" / "subagents", "investigador", "worker")

    await h.reloader.reload("viernes")
    worker = await h.build("t1")

    assert [s.name for s in worker.spec.skills] == ["nueva"]
    assert set(worker.spec.subagents) == {"investigador"}
    await h.factory.close()


async def test_concurrent_reloads_of_the_same_agent_are_serialised(h: Harness) -> None:
    order: list[str] = []

    class SlowManager(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            order.append("start")
            await asyncio.sleep(0.01)
            order.append("end")
            await super().start(tool_config, server_filter)

    h.factory.pool._manager_factory = lambda settings: SlowManager()  # noqa: SLF001

    await asyncio.gather(h.reloader.reload("viernes"), h.reloader.reload("viernes"))

    assert order == ["start", "end", "start", "end"]
    assert len(h.events.payloads(CONFIG_RELOADED)) == 2
    await h.factory.close()


async def test_front_change_only_asks_for_a_restart(h: Harness) -> None:
    await h.reloader.reload("jarvis")

    assert h.events.events == []
    assert len(h.notices) == 1 and "jarvis" in h.notices[0] and "reinicio" in h.notices[0]


async def test_unknown_agent_is_ignored(h: Harness) -> None:
    await h.reloader.reload("nadie")

    assert h.events.events == [] and h.notices == []


# --- exact notices and events --------------------------------------------------------------------

import logging  # noqa: E402

from tony.core.orchestrator.reload import FAILED_NOTICE, RELOADED_NOTICE, RESTART_NOTICE  # noqa: E402


async def test_notices_have_the_exact_text(h: Harness) -> None:
    h.write_tool_json({"mcpServers": {"fake": FAKE, "fake2": FAKE}})
    await h.reloader.reload("viernes")
    h.write_tool_json("{bad")
    await h.reloader.reload("viernes")
    await h.reloader.reload("jarvis")

    error = h.events.payloads(CONFIG_RELOAD_FAILED)[0]["error"]
    assert h.notices == [
        "Configuración de 'viernes' recargada; servidores MCP: fake, fake2.",
        f"No se pudo recargar 'viernes'; se conserva la configuración anterior: {error}",
        "El agente 'jarvis' ha cambiado, pero el front requiere reinicio de tony chat.",
    ]
    assert h.notices[0] == RELOADED_NOTICE.format(agent="viernes", servers="fake, fake2")
    assert h.notices[1] == FAILED_NOTICE.format(agent="viernes", error=error)
    assert h.notices[2] == RESTART_NOTICE.format(agent="jarvis")
    assert error.startswith("agente viernes: tool.json inválido")
    await h.factory.close()


async def test_reload_without_servers_says_none(h: Harness) -> None:
    h.write_tool_json({"native": ["read_skill"]})

    await h.reloader.reload("viernes")

    assert h.events.payloads(CONFIG_RELOADED) == [{"agent": "viernes", "servers": []}]
    assert h.notices == ["Configuración de 'viernes' recargada; servidores MCP: ninguno."]
    await h.factory.close()


async def test_unknown_agent_is_logged_by_name(h: Harness, caplog) -> None:
    with caplog.at_level(logging.INFO):
        await h.reloader.reload("nadie")

    assert any("nadie" in record.message for record in caplog.records)


async def test_generation_swap_failure_is_reported_and_keeps_the_old_one(h: Harness) -> None:
    await h.build("t1")
    current = h.factory.pool.current

    class Broken(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            raise RuntimeError("npx missing")

    h.factory.pool._manager_factory = lambda settings: Broken()  # noqa: SLF001
    h.write_tool_json({"mcpServers": {"fake": FAKE, "fake2": FAKE}})

    await h.reloader.reload("viernes")

    assert h.events.payloads(CONFIG_RELOAD_FAILED) == [{"agent": "viernes", "error": "npx missing"}]
    assert h.factory.pool.current is current
    await h.factory.close()


# --- spec and generation are published together (review of change 03) --------------------------


class GatedSecondManager:
    """Managers after the first wait on `gate` before completing their start."""

    def __init__(self, h: Harness) -> None:
        self.h = h
        self.gate = asyncio.Event()

    def __call__(self, settings) -> FakeManager:
        gate = self.gate if self.h.managers else None

        class Manager(FakeManager):
            async def start(self, tool_config, server_filter=None) -> None:
                if gate is not None:
                    await gate.wait()
                await super().start(tool_config, server_filter)

        manager = Manager()
        self.h.managers.append(manager)
        return manager


def add_skill_and_server(h: Harness) -> None:
    skill = h.agents / "viernes" / "skills" / "nueva" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: nueva\ndescription: d\n---\ncuerpo\n", encoding="utf-8")
    h.write_tool_json({"mcpServers": {"fake": FAKE, "fake2": FAKE}})


async def test_new_tasks_keep_the_old_spec_and_catalog_until_the_new_generation_starts(
    h: Harness,
) -> None:
    gated = GatedSecondManager(h)
    h.factory.pool._manager_factory = gated  # noqa: SLF001
    await h.build("t1")
    add_skill_and_server(h)
    reload = asyncio.ensure_future(h.reloader.reload("viernes"))
    for _ in range(5):
        await asyncio.sleep(0)

    during = await h.build("t2")
    assert during.spec.skills == [] and set(during.spec.tools.mcpServers) == {"fake"}
    assert during.catalog is h.managers[0].catalog
    assert h.events.payloads(CONFIG_RELOADED) == []

    gated.gate.set()
    await asyncio.wait_for(reload, 1)
    after = await h.build("t3")
    assert [s.name for s in after.spec.skills] == ["nueva"]
    assert after.catalog is h.managers[1].catalog
    assert h.managers[1].started_with == after.spec.tools
    await h.factory.close()


async def test_swap_failure_keeps_the_old_spec_for_new_tasks(h: Harness) -> None:
    await h.build("t1")

    class Broken(FakeManager):
        async def start(self, tool_config, server_filter=None) -> None:
            raise RuntimeError("npx missing")

    h.factory.pool._manager_factory = lambda settings: Broken()  # noqa: SLF001
    add_skill_and_server(h)

    await h.reloader.reload("viernes")
    worker = await h.build("t2")

    assert worker.spec.skills == [] and set(worker.spec.tools.mcpServers) == {"fake"}
    assert worker.catalog is h.managers[0].catalog
    await h.factory.close()


async def test_cancelled_reload_keeps_the_old_spec_and_reports_it(h: Harness) -> None:
    gated = GatedSecondManager(h)
    h.factory.pool._manager_factory = gated  # noqa: SLF001
    await h.build("t1")
    add_skill_and_server(h)
    reload = asyncio.ensure_future(h.reloader.reload("viernes"))
    for _ in range(5):
        await asyncio.sleep(0)

    reload.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reload
    gated.gate.set()

    failed = h.events.payloads(CONFIG_RELOAD_FAILED)
    assert len(failed) == 1 and failed[0]["agent"] == "viernes"
    assert "cancel" in failed[0]["error"]
    worker = await h.build("t2")
    assert worker.spec.skills == [] and worker.catalog is h.managers[0].catalog
    await asyncio.wait_for(h.factory.close(), 1)
    assert all(m.stopped for m in h.managers)
