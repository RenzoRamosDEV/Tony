"""Building the child worker: effective catalog, own servers, routed calls (specs/subagents)."""

from __future__ import annotations

from pathlib import Path

from tests.apps.cli_helpers import FakeManager
from tests.core.runner_helpers import mcp_tool
from tests.fakes.gates import AutoConfirmGate
from tony.core.config import load_settings
from tony.core.loader import AgentSpec, StdioServer, ToolConfig
from tony.core.mcp import ToolCatalog
from tony.core.runner.cancel import CancelToken
from tony.core.skills import SkillSpec
from tony.core.subagents.builder import ChildWorker, SubagentWorkerBuilder

SETTINGS = load_settings(None)
FS = StdioServer(command="fs")
FETCH = StdioServer(command="fetch")
SKILL = SkillSpec(name="fuentes", description="d", body="busca bien", path=Path("/s"))


def parent(allow: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        name="viernes",
        role="worker",
        model="claude-sonnet",
        path=Path("/v"),
        tools=ToolConfig(mcpServers={"fs": FS}, allow=allow, confirm=["fs.write_file"]),
    )


def child(tools: ToolConfig | None = None) -> AgentSpec:
    return AgentSpec(
        name="investigador",
        role="worker",
        model="claude-haiku",
        path=Path("/v/subagents/investigador"),
        tools=tools or ToolConfig(),
        parent="viernes",
        skills=[SKILL],
    )


def parent_manager() -> FakeManager:
    tools = {"fs": [mcp_tool("read_file"), mcp_tool("write_file")]}
    return FakeManager(ToolCatalog.build(tools, None, ["fs.write_file"]))


class Recorder:
    def __init__(self) -> None:
        self.runner_calls: list[tuple] = []
        self.managers: list[FakeManager] = []

    def runner_factory(self, settings, task_id, gate, call, token, handlers):
        self.runner_calls.append((settings, task_id, gate, call, token, handlers))
        return object()

    def manager_factory(self, settings):
        manager = FakeManager(
            ToolCatalog.build(
                {"fetch": [mcp_tool("fetch")], "fs": [mcp_tool("read_file")]}, None, []
            )
        )
        self.managers.append(manager)
        return manager


async def build(
    recorder: Recorder, parent_spec: AgentSpec, child_spec: AgentSpec, manager: FakeManager
) -> tuple[ChildWorker, AutoConfirmGate, CancelToken]:
    builder = SubagentWorkerBuilder(SETTINGS, recorder.runner_factory, recorder.manager_factory)
    gate, token = AutoConfirmGate(True), CancelToken()
    worker = await builder.build(parent_spec, child_spec, manager, gate, token, "s1")
    return worker, gate, token


async def test_child_without_tool_json_gets_the_parent_catalog_and_no_manager() -> None:
    recorder, manager = Recorder(), parent_manager()

    worker, gate, token = await build(recorder, parent(), child(), manager)

    assert worker.catalog.qualified_names() == ["fs.read_file", "fs.write_file"]
    assert worker.catalog.get("fs.write_file").needs_confirm is True
    assert worker.spec is not None and worker.spec.name == "investigador"
    assert recorder.managers == []
    settings, task_id, got_gate, call, got_token, handlers = recorder.runner_calls[0]
    assert (task_id, got_gate, got_token) == ("s1", gate, token)
    assert call == manager.call


async def test_child_allow_narrows_the_parent_catalog() -> None:
    recorder, manager = Recorder(), parent_manager()

    worker, *_ = await build(recorder, parent(), child(ToolConfig(allow=["fs.read_file"])), manager)

    assert worker.catalog.qualified_names() == ["fs.read_file"]


async def test_child_with_a_new_server_starts_its_own_manager_and_routes_calls() -> None:
    recorder, manager = Recorder(), parent_manager()
    spec = child(ToolConfig(mcpServers={"fetch": FETCH}))

    worker, *_ = await build(recorder, parent(), spec, manager)

    own = recorder.managers[0]
    assert own.server_filter == ["fetch"]
    assert set(own.started_with.mcpServers) == {"fs", "fetch"}
    assert sorted(worker.catalog.qualified_names()) == [
        "fetch.fetch",
        "fs.read_file",
        "fs.write_file",
    ]
    call = recorder.runner_calls[0][3]
    assert (await call("fetch.fetch", {"url": "u"}, 5)).content == "fetch.fetch ok"
    assert (await call("fs.read_file", {"path": "p"}, 5)).content == "fs.read_file ok"
    assert own.calls == [("fetch.fetch", {"url": "u"})]
    assert manager.calls == [("fs.read_file", {"path": "p"})]


async def test_new_server_tools_pass_through_the_parent_allow() -> None:
    recorder, manager = Recorder(), parent_manager()
    spec = child(ToolConfig(mcpServers={"fetch": FETCH}))

    worker, *_ = await build(recorder, parent(allow=["fs.*"]), spec, manager)

    assert "fetch.fetch" not in worker.catalog


async def test_close_stops_only_the_child_manager() -> None:
    recorder, manager = Recorder(), parent_manager()
    spec = child(ToolConfig(mcpServers={"fetch": FETCH}))
    worker, *_ = await build(recorder, parent(), spec, manager)

    await worker.close()
    await worker.close()

    assert recorder.managers[0].stopped is True
    assert manager.stopped is False


async def test_child_without_new_servers_closes_without_stopping_anything() -> None:
    recorder, manager = Recorder(), parent_manager()
    worker, *_ = await build(recorder, parent(), child(), manager)

    await worker.close()

    assert manager.stopped is False


async def test_child_handlers_read_their_own_skills_and_cannot_run_subagents() -> None:
    recorder, manager = Recorder(), parent_manager()

    await build(recorder, parent(), child(), manager)

    handlers = recorder.runner_calls[0][5]
    assert await handlers.read_skill("fuentes") == "busca bien"
    assert not hasattr(handlers, "run_subagent")


# --- exact policy application --------------------------------------------------------------------

import logging  # noqa: E402

from tony.core.mcp import ToolCallOutcome  # noqa: E402
from tony.core.subagents.builder import CompositeToolCaller  # noqa: E402


async def test_own_manager_gets_the_merged_servers_child_allow_and_union_confirm() -> None:
    recorder, manager = Recorder(), parent_manager()
    spec = child(
        ToolConfig(
            mcpServers={"fetch": FETCH}, allow=["fetch.*", "fs.read_file"], confirm=["fetch.fetch"]
        )
    )

    worker, *_ = await build(recorder, parent(), spec, manager)

    own = recorder.managers[0]
    assert own.started_with == ToolConfig(
        mcpServers={"fs": FS, "fetch": FETCH},
        allow=["fetch.*", "fs.read_file"],
        confirm=["fs.write_file", "fetch.fetch"],
    )
    assert sorted(worker.catalog.qualified_names()) == ["fetch.fetch", "fs.read_file"]


async def test_nested_parent_rejects_new_servers_with_an_exact_warning(caplog) -> None:
    recorder, manager = Recorder(), parent_manager()
    nested_parent = parent().model_copy(update={"parent": "abuelo"})
    spec = child(ToolConfig(mcpServers={"fetch": FETCH}))

    with caplog.at_level(logging.WARNING):
        worker, *_ = await build(recorder, nested_parent, spec, manager)

    assert recorder.managers == []
    assert "fetch.fetch" not in worker.catalog
    assert [r.message for r in caplog.records] == [
        "investigador: el subagente declara el servidor MCP 'fetch' pero su padre ya es un "
        "subagente; se ignora"
    ]


async def test_composite_caller_routes_by_the_server_prefix_only() -> None:
    calls: list[tuple[str, str]] = []

    def caller(name: str):
        async def call(qualified, args, timeout):
            calls.append((name, qualified))
            return ToolCallOutcome(ok=True, content=name, duration_ms=1)

        return call

    composite = CompositeToolCaller(caller("parent"), caller("own"), {"fetch"})

    assert (await composite("fetch.fetch", {}, 1)).content == "own"
    assert (await composite("fetchx.fetch", {}, 1)).content == "parent"
    assert (await composite("fs.read_file", {}, 1)).content == "parent"
    assert calls == [("own", "fetch.fetch"), ("parent", "fetchx.fetch"), ("parent", "fs.read_file")]
