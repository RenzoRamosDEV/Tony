"""Hot reload of a worker's tool.json: validate, swap the MCP generation, notify."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from tony.core.config import EnvMap, TonySettings
from tony.core.doctor.validate import validate_agent
from tony.core.loader import load_agent
from tony.core.orchestrator.worker import SdkWorkerFactory
from tony.core.runner import EventSink

CONFIG_RELOADED = "config.reloaded"
CONFIG_RELOAD_FAILED = "config.reload_failed"
RESTART_NOTICE = "El agente '{agent}' ha cambiado, pero el front requiere reinicio de tony chat."
RELOADED_NOTICE = "Configuración de '{agent}' recargada; servidores MCP: {servers}."
FAILED_NOTICE = "No se pudo recargar '{agent}'; se conserva la configuración anterior: {error}"
CANCELLED_ERROR = "recarga cancelada antes de arrancar los servidores nuevos"

Notify = Callable[[str], Awaitable[None]]
logger = logging.getLogger(__name__)


class AgentReloader:
    def __init__(
        self,
        agents_dir: Path,
        settings: TonySettings,
        env: EnvMap,
        factory: SdkWorkerFactory,
        events: EventSink,
        notify: Notify,
    ) -> None:
        self._agents_dir = agents_dir
        self._settings = settings
        self._env = env
        self._factory = factory
        self._events = events
        self._notify = notify
        self._locks: dict[str, asyncio.Lock] = {}

    async def reload(self, agent: str) -> None:
        if agent == self._settings.front:
            await self._notify(RESTART_NOTICE.format(agent=agent))
            return
        if agent != self._settings.worker:
            logger.info("cambio en el agente '%s', que no está en uso; se ignora", agent)
            return
        async with self._locks.setdefault(agent, asyncio.Lock()):
            failures = [
                r
                for r in validate_agent(self._agents_dir, agent, self._settings, self._env)
                if r.failed
            ]
            if failures:
                await self._failed(agent, "; ".join(f"{r.name}: {r.detail}" for r in failures))
                return
            await self._apply(agent)

    async def _apply(self, agent: str) -> None:
        spec = load_agent(self._agents_dir / agent, self._settings, self._env)
        try:
            await self._factory.reload_spec(spec)
        except asyncio.CancelledError:
            await self._failed(agent, CANCELLED_ERROR)
            raise
        except Exception as exc:  # noqa: BLE001 - the previous spec and generation stay
            await self._failed(agent, str(exc) or exc.__class__.__name__)
            return
        servers = list(spec.tools.mcpServers)
        self._events.emit(CONFIG_RELOADED, {"agent": agent, "servers": servers})
        await self._notify(
            RELOADED_NOTICE.format(agent=agent, servers=", ".join(servers) or "ninguno")
        )

    async def _failed(self, agent: str, error: str) -> None:
        self._events.emit(CONFIG_RELOAD_FAILED, {"agent": agent, "error": error})
        await self._notify(FAILED_NOTICE.format(agent=agent, error=error))
