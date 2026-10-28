"""SdkWorkerFactory.status(): read-only view of the MCP servers of the generation in use."""

from __future__ import annotations

from pathlib import Path

from tests.apps.cli_helpers import FakeManager
from tests.fakes.gates import AutoConfirmGate
from tests.fakes.sinks import ListEventSink
from tony.core.config import load_settings
from tony.core.loader import AgentSpec
from tony.core.mcp import McpServerStatus
from tony.core.orchestrator.task import Task
from tony.core.orchestrator.worker import SdkWorkerFactory
from tony.core.runner import TaskRequest
from tony.core.runner.cancel import CancelToken

READY = {"filesystem": McpServerStatus("filesystem", "ready", None, 11, None)}


def make_factory(tmp_path: Path, managers: list[FakeManager]) -> SdkWorkerFactory:
    def manager_factory(settings) -> FakeManager:
        manager = FakeManager()
        manager.statuses = READY
        managers.append(manager)
        return manager

    spec = AgentSpec(name="viernes", role="worker", model="claude-sonnet", path=Path("/tmp/v"))
    return SdkWorkerFactory(
        load_settings(None),
        spec,
        logs_dir=tmp_path,
        secrets=[],
        manager_factory=manager_factory,
        runner_factory=lambda *args, **kwargs: object(),
    )


async def test_status_is_empty_before_any_generation_starts_and_starts_nothing(tmp_path) -> None:
    managers: list[FakeManager] = []
    factory = make_factory(tmp_path, managers)

    assert factory.status() == {}
    assert managers == []
    await factory.close()


async def test_status_reports_the_manager_statuses_after_the_first_worker(tmp_path) -> None:
    managers: list[FakeManager] = []
    factory = make_factory(tmp_path, managers)
    await factory.build_worker(
        Task("t1", TaskRequest(objetivo="a")), ListEventSink(), CancelToken(), AutoConfirmGate(True)
    )

    assert factory.status() == READY
    assert len(managers) == 1
    await factory.close()
