from typing import Protocol

from tony.core.guard.policy import Policy
from tony.core.loader.tool_json import ToolSpec


class PolicySource(Protocol):
    def current(self) -> Policy: ...


class ToolSpecSource(Protocol):
    def spec_for(self, key: str) -> ToolSpec: ...


class StaticPolicy:
    """The policy loaded once for a single task (`tony run`)."""

    def __init__(self, policy: Policy) -> None:
        self._policy = policy

    def current(self) -> Policy:
        return self._policy
