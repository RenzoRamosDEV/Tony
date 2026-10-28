"""Watches agents/**/tool/tool.json and reports the affected top-level agent."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import watchfiles

DEBOUNCE_MS = 500
STOP_TIMEOUT_S = 1.0
TOOL_JSON_PARTS = ("tool", "tool.json")

OnChange = Callable[[str], Awaitable[None]]
logger = logging.getLogger(__name__)


def is_tool_json(change: Any, path: str) -> bool:
    return tuple(Path(path).parts[-2:]) == TOOL_JSON_PARTS


def agent_of(agents_dir: Path, path: str) -> str | None:
    try:
        relative = Path(path).resolve().relative_to(Path(agents_dir).resolve())
    except ValueError:
        return None
    return relative.parts[0] if len(relative.parts) > 1 else None


class ConfigWatcher:
    def __init__(
        self,
        agents_dir: Path,
        on_change: OnChange,
        watch: Callable[..., Any] | None = None,
        debounce_ms: int = DEBOUNCE_MS,
    ) -> None:
        self._agents_dir = agents_dir
        self._on_change = on_change
        self._watch = watch or watchfiles.awatch
        self._debounce_ms = debounce_ms
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(self._stop))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if self._stop is not None:
            self._stop.set()
        if task is not None:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(task, STOP_TIMEOUT_S)

    async def _run(self, stop: asyncio.Event) -> None:
        async for changes in self._watch(
            self._agents_dir,
            watch_filter=is_tool_json,
            stop_event=stop,
            debounce=self._debounce_ms,
        ):
            affected = {agent_of(self._agents_dir, path) for _, path in changes}
            for agent in sorted(a for a in affected if a):
                await self._notify(agent)

    async def _notify(self, agent: str) -> None:
        try:
            await self._on_change(agent)
        except Exception:  # noqa: BLE001 - one failed reload must not stop watching
            logger.exception("error al recargar el agente '%s'", agent)
