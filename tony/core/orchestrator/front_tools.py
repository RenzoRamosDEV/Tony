import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from pydantic import ValidationError

from tony.core.events import core_events
from tony.core.events.core_events import Publisher, ReplyMode
from tony.core.events.messages import TaskRequest, TaskResult
from tony.core.mcp.native import NATIVE_SERVER
from tony.core.memory.preferences import REPLY_MODES, PreferencesFile
from tony.core.orchestrator.ports import ProxiedTool, ToolReply

WAITING_PHRASE = "Un momento, señor; estoy en ello."
WAITING_AFTER_S = 3.0
LOCKED = json.dumps({"error": "locked"})

WorkerRunner = Callable[[TaskRequest], Awaitable[TaskResult]]


class Gate(Protocol):
    async def ensure_unlocked(self) -> bool: ...


class FrontTools:
    """The front agent's control tools. They bypass the guard: they only touch Tony's memory or
    start a worker task whose own tool calls are each judged."""

    def __init__(
        self,
        *,
        front_agent: str,
        preferences: PreferencesFile,
        gate: Gate,
        run_worker: WorkerRunner,
        publish: Publisher,
        waiting_after_s: float = WAITING_AFTER_S,
    ) -> None:
        self._front_agent = front_agent
        self._preferences = preferences
        self._gate = gate
        self._run_worker = run_worker
        self._publish = publish
        self.waiting_after_s = waiting_after_s

    def tools(self) -> list[ProxiedTool]:
        return [
            _tool(
                "delegate",
                "Encarga una tarea al agente ejecutor y devuelve su resultado "
                "{resumen, datos, pasos, errores}.",
                {
                    "objetivo": {"type": "string"},
                    "contexto": {"type": "string"},
                    "restricciones": {"type": "array", "items": {"type": "string"}},
                },
                ["objetivo"],
                self.delegate,
            ),
            _tool(
                "remember",
                "Guarda una preferencia duradera del usuario.",
                {"text": {"type": "string"}},
                ["text"],
                self.remember,
            ),
            _tool(
                "set_reply_mode",
                "Cambia el modo de respuesta: auto, voice, text o both.",
                {"mode": {"type": "string", "enum": list(REPLY_MODES)}},
                ["mode"],
                self.set_reply_mode,
            ),
        ]

    async def delegate(self, args: dict[str, Any]) -> ToolReply:
        try:
            request = TaskRequest.model_validate(args)
        except ValidationError as error:
            return _error(str(error))
        if not await self._gate.ensure_unlocked():
            return ToolReply(text=LOCKED, is_error=True)
        task = asyncio.create_task(self._run_worker(request))
        try:
            done, _ = await asyncio.wait({task}, timeout=self.waiting_after_s)
            if not done:
                self._publish(core_events.progress(self._front_agent, WAITING_PHRASE))
            result = await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        return ToolReply(text=result.model_dump_json())

    async def remember(self, args: dict[str, Any]) -> ToolReply:
        text = args.get("text")
        if not isinstance(text, str):
            return _error("text must be a string")
        try:
            self._preferences.append_line(text)
        except ValueError as error:
            return _error(str(error))
        return ToolReply(text="preferencia guardada")

    async def set_reply_mode(self, args: dict[str, Any]) -> ToolReply:
        mode = str(args.get("mode"))
        try:
            self._preferences.set_reply_mode(mode)
        except ValueError as error:
            return _error(str(error))
        self._publish(core_events.reply_mode(cast(ReplyMode, mode)))
        return ToolReply(text=f"modo de respuesta: {mode}")


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    handler: Callable[[dict[str, Any]], Awaitable[ToolReply]],
) -> ProxiedTool:
    return ProxiedTool(
        id=f"{NATIVE_SERVER}.{name}",
        description=description,
        input_schema={"type": "object", "properties": properties, "required": required},
        handler=handler,
    )


def _error(message: str) -> ToolReply:
    return ToolReply(text=json.dumps({"error": message}, ensure_ascii=False), is_error=True)
