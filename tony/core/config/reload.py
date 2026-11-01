from collections.abc import Collection
from pathlib import Path
from typing import Protocol

from tony.core.config.errors import DefinitionError
from tony.core.guard.policy import Policy, load_policy
from tony.core.loader.tool_json import ToolSpec, load_tool_spec


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


class LivePolicy:
    """The guard's last valid policy; a failed reload keeps the previous one."""

    def __init__(self, root: Path, guard: str, policy: Policy) -> None:
        self._root = root
        self._guard = guard
        self._policy = policy

    def current(self) -> Policy:
        return self._policy

    def reload(self) -> DefinitionError | None:
        try:
            self._policy = load_policy(self._root, self._guard)
        except DefinitionError as error:
            return error
        return None


class LiveToolSpecs:
    """Last valid tool declaration per agent key; uncached keys are read from disk."""

    def __init__(self, root: Path, *, native_tools: Collection[str]) -> None:
        self._root = root
        self._native_tools = native_tools
        self._specs: dict[str, ToolSpec] = {}

    def spec_for(self, key: str) -> ToolSpec:
        cached = self._specs.get(key)
        if cached is not None:
            return cached
        return self._read(key)

    def cached(self, key: str) -> ToolSpec | None:
        return self._specs.get(key)

    def reload(self, key: str) -> DefinitionError | None:
        try:
            self._specs[key] = self._read(key)
        except DefinitionError as error:
            return error
        return None

    def _read(self, key: str) -> ToolSpec:
        return load_tool_spec(self._root, key, native_tools=self._native_tools)
