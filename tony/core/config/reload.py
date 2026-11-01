import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO

from tony.core.config.errors import DefinitionError
from tony.core.config.placeholders import SecretMasker
from tony.core.config.secrets import load_variables
from tony.core.events import core_events
from tony.core.events.core_events import MaskingPublisher, Publisher
from tony.core.guard.policy import Policy, load_policy, policy_file
from tony.core.loader.tool_json import McpServer, ToolSpec, load_tool_spec
from tony.core.logging.task_log import Clock, utc_now
from tony.core.mcp.manager import McpManager

RELOAD_SOURCE = "reload"
REMOVED_REASON = "removed from tool.json"
TOOL_JSON = ("tool", "tool.json")

Probe = Callable[[str, str, McpServer], Awaitable[None]]
"""Connects, lists and closes one server of an agent key, publishing its `mcp_status`."""
Change = tuple[Literal["policy"], None] | tuple[Literal["tools"], str]


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


@dataclass(frozen=True)
class ServerDiff:
    added: list[str]
    changed: list[str]
    removed: list[str]


def diff_servers(old: Mapping[str, McpServer], new: Mapping[str, McpServer]) -> ServerDiff:
    return ServerDiff(
        added=[name for name in new if name not in old],
        changed=[
            name for name in new if name in old and old[name].model_dump() != new[name].model_dump()
        ],
        removed=[name for name in old if name not in new],
    )


def classify(root: Path, guard: str, path: Path) -> Change | None:
    """Which watched configuration a changed path is, if any."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if parts == Path(policy_file(guard)).parts:
        return ("policy", None)
    if len(parts) == 4 and parts[0] == "agents" and parts[2:] == TOOL_JSON:
        return ("tools", parts[1])
    if (
        len(parts) == 6
        and parts[0] == "agents"
        and parts[2] == "subagents"
        and (parts[4:] == TOOL_JSON)
    ):
        return ("tools", f"{parts[1]}/{parts[3]}")
    return None


class ConfigReloader:
    """Applies batches of changed configuration files to the live sources."""

    def __init__(
        self,
        root: Path,
        guard: str,
        policy: LivePolicy,
        tools: LiveToolSpecs,
        *,
        publish: Publisher,
        probe: Probe,
        stderr: TextIO = sys.stderr,
        clock: Clock = utc_now,
    ) -> None:
        self._root = root
        self._guard = guard
        self._policy = policy
        self._tools = tools
        self._publish = publish
        self._probe = probe
        self._stderr = stderr
        self._clock = clock
        self._probes: set[asyncio.Task[None]] = set()

    async def run(self, changes: AsyncIterator[set[Path]]) -> None:
        try:
            async for batch in changes:
                await self.handle(batch)
        finally:
            await self._cancel_probes()

    async def handle(self, batch: set[Path]) -> None:
        for path in sorted(batch):
            change = classify(self._root, self._guard, path)
            if change is None:
                continue
            kind, key = change
            if kind == "policy":
                self._report(self._policy.reload())
            else:
                self._reload_tools(key)

    async def wait_idle(self) -> None:
        await asyncio.gather(*self._probes, return_exceptions=True)

    def _reload_tools(self, key: str) -> None:
        previous = self._tools.cached(key)
        error = self._tools.reload(key)
        if error is not None:
            self._report(error)
            return
        current = self._tools.spec_for(key).mcp_servers
        diff = diff_servers(previous.mcp_servers if previous else {}, current)
        for name in diff.removed:
            self._publish(
                core_events.mcp_status(
                    key, name, up=False, reason=REMOVED_REASON, clock=self._clock
                )
            )
        for name in [*diff.added, *diff.changed]:
            task = asyncio.create_task(self._probe(key, name, current[name]))
            self._probes.add(task)
            task.add_done_callback(self._probes.discard)

    def _report(self, error: DefinitionError | None) -> None:
        if error is None:
            return
        self._publish(core_events.error(RELOAD_SOURCE, str(error), clock=self._clock))
        print(f"tony: warning: {error}", file=self._stderr)

    async def _cancel_probes(self) -> None:
        for task in self._probes:
            task.cancel()
        await self.wait_idle()


class _Discard:
    def emit(self, event: dict) -> None:
        return None


def mcp_probe(
    root: Path,
    *,
    environ: Mapping[str, str],
    publish: Publisher,
    clock: Clock = utc_now,
    connect_timeout: float = 10.0,
) -> Probe:
    """Probe adapter over McpManager: connect, list and close a single server."""

    async def probe(key: str, name: str, server: McpServer) -> None:
        variables = load_variables(root, environ)
        masker = SecretMasker(variables.env_file_values.values())
        masked = MaskingPublisher(masker, publish)
        manager = McpManager(
            ToolSpec(mcp_servers={name: server}),
            variables=variables,
            masker=masker,
            sink=_Discard(),
            log_dir=root / "logs" / "mcp",
            connect_timeout=connect_timeout,
            on_status=lambda server_name, status: masked(
                core_events.mcp_status(
                    key, server_name, up=status.up, reason=status.reason, clock=clock
                )
            ),
        )
        async with manager:
            pass

    return probe
