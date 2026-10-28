"""Terminal adapter of the Channel port: replies to stdout, everything else to stderr."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any, TextIO

from tony.apps.cli.confirm_gate import AFFIRMATIVE
from tony.apps.cli.stdin_reader import LineSource
from tony.core.channels.ports import (
    AssistantReply,
    AssistantWait,
    ChannelMessage,
    NeedsConfirmation,
    Notice,
    TaskProgress,
)
from tony.core.orchestrator.errors import OrchestratorError

Confirm = Callable[[str, bool, str, dict[str, Any]], Awaitable[None]]

SPEAKER = "🔊"
CONFIRM_PROMPT = "{worker} quiere ejecutar {tool} {args}. ¿Confirmas? [s/N] "
NO_ANSWER = "\nSin respuesta en {timeout:g} s: la tarea se cancela por falta de confirmación.\n"
STALE_CONFIRMATION = "La confirmación ya no es válida (caducada o resuelta); la tarea se canceló.\n"


class CliChannel:
    def __init__(
        self,
        worker_name: str,
        lines: LineSource,
        confirm: Confirm,
        confirm_timeout_s: float,
        out: TextIO | None = None,
        stdout: TextIO | None = None,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._worker_name = worker_name
        self._lines = lines
        self._confirm = confirm
        self._confirm_timeout_s = confirm_timeout_s
        self._out = out
        self._stdout = stdout
        self._lock = lock or asyncio.Lock()

    async def send(self, message: ChannelMessage) -> None:
        if isinstance(message, AssistantReply):
            self._print_reply(message)
        elif isinstance(message, AssistantWait):
            self._err(f"{message.text}\n")
        elif isinstance(message, TaskProgress):
            self._err(f"· {message.tool}\n")
        elif isinstance(message, Notice):
            self._err(f"{message.text}\n")
        elif isinstance(message, NeedsConfirmation):
            await self._ask(message)
        else:
            return

    def _print_reply(self, reply: AssistantReply) -> None:
        stdout = self._stdout or sys.stdout
        if reply.mode != "text" and reply.speech_text:
            stdout.write(f"{SPEAKER} {reply.speech_text}\n")
        stdout.write(f"{reply.display_text}\n")
        stdout.flush()

    async def _ask(self, request: NeedsConfirmation) -> None:
        args = json.dumps(request.args, sort_keys=True, ensure_ascii=False)
        async with self._lock:
            self._err(CONFIRM_PROMPT.format(worker=self._worker_name, tool=request.tool, args=args))
            try:
                answer = await asyncio.wait_for(self._lines.readline(), self._confirm_timeout_s)
            except TimeoutError:
                self._err(NO_ANSWER.format(timeout=self._confirm_timeout_s))
                return
        approved = answer is not None and answer.strip().lower() in AFFIRMATIVE
        try:
            await self._confirm(request.confirmation_id, approved, request.tool, request.args)
        except OrchestratorError:
            self._err(STALE_CONFIRMATION)

    def _err(self, text: str) -> None:
        out = self._out or sys.stderr
        out.write(text)
        out.flush()
