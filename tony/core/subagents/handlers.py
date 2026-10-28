"""Native tool handlers of a worker: skills for every worker, subagents only at depth 0."""

from __future__ import annotations

from tony.core.loader import AgentSpec
from tony.core.runner import TaskRequest, TaskResult
from tony.core.skills.index import find_skill
from tony.core.subagents.launcher import SubagentLauncher


class SkillToolHandlers:
    def __init__(self, spec: AgentSpec) -> None:
        self._spec = spec

    async def read_skill(self, name: str) -> str:
        return find_skill(self._spec.skills, name).body


class WorkerToolHandlers(SkillToolHandlers):
    def __init__(self, spec: AgentSpec, launcher: SubagentLauncher) -> None:
        super().__init__(spec)
        self._launcher = launcher

    async def run_subagent(self, name: str, request: TaskRequest) -> TaskResult:
        return await self._launcher.run_subagent(name, request)
