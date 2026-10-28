"""Builds the worker of a subtask: parent tools (already connected) plus its own servers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from tony.core.config import TonySettings
from tony.core.loader import AgentSpec, ToolConfig
from tony.core.mcp import ConfirmGate, ToolCallOutcome, ToolCatalog
from tony.core.mcp.owner import CLOSE_BUDGET_S, ManagerOwner
from tony.core.mcp.ports import ManagerFactory, ToolManager
from tony.core.runner import AgentRunner
from tony.core.runner.cancel import CancelToken
from tony.core.runner.factory import WorkerRunnerFactory
from tony.core.runner.proxy import ToolCaller
from tony.core.subagents.handlers import SkillToolHandlers
from tony.core.subagents.permissions import ChildPolicy, child_policy, effective_catalog

logger = logging.getLogger(__name__)


@dataclass
class ChildWorker:
    runner: AgentRunner
    spec: AgentSpec
    catalog: ToolCatalog
    close: Callable[[], Awaitable[None]]


class CompositeToolCaller:
    """Routes each call to the manager that owns the tool's server."""

    def __init__(self, parent: ToolCaller, own: ToolCaller, own_servers: set[str]) -> None:
        self._parent = parent
        self._own = own
        self._own_servers = own_servers

    async def __call__(
        self, qualified: str, args: dict[str, Any], timeout: float
    ) -> ToolCallOutcome:
        server = qualified.partition(".")[0]
        caller = self._own if server in self._own_servers else self._parent
        return await caller(qualified, args, timeout)


class SubagentWorkerBuilder:
    def __init__(
        self,
        settings: TonySettings,
        runner_factory: WorkerRunnerFactory,
        manager_factory: ManagerFactory,
        close_budget_s: float = CLOSE_BUDGET_S,
    ) -> None:
        self._settings = settings
        self._runner_factory = runner_factory
        self._manager_factory = manager_factory
        self._close_budget_s = close_budget_s

    async def build(
        self,
        parent: AgentSpec,
        child: AgentSpec,
        parent_manager: ToolManager,
        gate: ConfirmGate,
        token: CancelToken,
        task_id: str,
    ) -> ChildWorker:
        policy = child_policy(
            parent.tools, child.tools, parent_is_subagent=parent.parent is not None
        )
        for warning in policy.warnings:
            logger.warning("%s: %s", child.name, warning)
        catalog = effective_catalog(parent_manager.catalog, policy)
        call: ToolCaller = parent_manager.call
        owner: ManagerOwner | None = None
        if policy.new_servers:
            owner = ManagerOwner(
                self._manager_factory(self._settings),
                _own_config(policy),
                self._close_budget_s,
                server_filter=policy.new_servers,
            )
            own = await owner.manager()
            catalog = catalog.merge(own.catalog.restrict(policy.allow_parent))
            call = CompositeToolCaller(parent_manager.call, own.call, set(policy.new_servers))
        runner = self._runner_factory(
            self._settings, task_id, gate, call, token, SkillToolHandlers(child)
        )
        return ChildWorker(runner, child, catalog, _closer(owner, child.name))


def _own_config(policy: ChildPolicy) -> ToolConfig:
    return ToolConfig(mcpServers=policy.servers, allow=policy.allow_child, confirm=policy.confirm)


def _closer(owner: ManagerOwner | None, child_name: str) -> Callable[[], Awaitable[None]]:
    async def close() -> None:
        nonlocal owner
        pending, owner = owner, None
        if pending is None:
            return
        try:
            await pending.stop()
        except Exception as exc:  # noqa: BLE001 - closing a child's servers never raises
            logger.warning("error al cerrar los servidores del subagente %s: %s", child_name, exc)

    return close
