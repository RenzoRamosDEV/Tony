"""Chat loop: prompt, local commands, reply-mode prefixes and Ctrl+C handling."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from collections.abc import Awaitable, Callable
from typing import TextIO

from tony.apps.cli.stdin_dispatcher import StdinDispatcher
from tony.core.channels.session import ChatSession, Memory
from tony.core.config import REPLY_MODES, TonySettings
from tony.core.runner.reply_mode import strip_prefix

PROMPT = "tú> "
CLOSE_TIMEOUT_S = 1.5
COMMANDS = "/mode, /memoria, /cancel, /salir"
CANCELLING = "\nCancelando la tarea… (otro Ctrl+C para salir)\n"


class ChatRepl:
    def __init__(
        self,
        session: ChatSession,
        lines: StdinDispatcher,
        memory: Memory,
        settings: TonySettings,
        out: TextIO | None = None,
        stdout: TextIO | None = None,
        close_timeout_s: float = CLOSE_TIMEOUT_S,
        before_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._before_close = before_close
        self._lines = lines
        self._memory = memory
        self._settings = settings
        self._out = out
        self._stdout = stdout
        self._close_timeout_s = close_timeout_s
        self._stopping = False
        self._cancel_requested = False
        self._current: asyncio.Task[None] | None = None

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        self._current = asyncio.current_task()
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(signal.SIGINT, self._on_sigint)
        try:
            while not self._stopping:
                try:
                    if not await self._step():
                        break
                except asyncio.CancelledError:
                    if not self._stopping:
                        raise
        finally:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(signal.SIGINT)
            await self._shutdown()
        return 0

    async def _step(self) -> bool:
        self._err(PROMPT)
        line = await self._lines.readline()
        if line is None:
            return False
        text = line.strip()
        if not text:
            return True
        prefix, _ = strip_prefix(text)
        if prefix is None and text.startswith("/"):
            return await self._command(text)
        self._cancel_requested = False
        await self._lines.during(self._session.handle(text), self._cancel)
        return True

    async def _command(self, text: str) -> bool:
        name, _, argument = text.partition(" ")
        argument = argument.strip()
        if name == "/salir":
            return False
        if name == "/mode":
            self._mode(argument)
        elif name == "/memoria":
            self._memoria()
        elif name == "/cancel":
            await self._cancel()
        else:
            self._err(f"Comando desconocido: {name}. Comandos: {COMMANDS}\n")
        return True

    def _mode(self, argument: str) -> None:
        if not argument:
            current = self._memory.settings.load().reply_mode or self._settings.reply_mode
            self._print(f"Modo de respuesta: {current}\n")
            return
        try:
            self._memory.settings.set_reply_mode(argument)
        except ValueError:
            self._err(f"Modo '{argument}' no válido. Valores: {', '.join(REPLY_MODES)}\n")
            return
        self._print(f"Modo de respuesta guardado: {argument}\n")

    def _memoria(self) -> None:
        lines = self._memory.preferences.read()
        self._print(("\n".join(lines) if lines else "(memoria vacía)") + "\n")

    async def _cancel(self) -> None:
        if not self._session.has_active_task:
            self._err("No hay ninguna tarea activa.\n")
            return
        await self._session.cancel_active()
        self._err("Tarea cancelada.\n")

    def _on_sigint(self) -> None:
        if self._session.has_active_task and not self._cancel_requested:
            self._cancel_requested = True
            self._err(CANCELLING)
            asyncio.ensure_future(self._session.cancel_active())
            return
        self._stopping = True
        self._err("\n")
        if self._current is not None:
            self._current.cancel()

    async def _shutdown(self) -> None:
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            if self._before_close is not None:
                await self._before_close()
            await asyncio.wait_for(self._session.close(), self._close_timeout_s)

    def _print(self, text: str) -> None:
        stdout = self._stdout or sys.stdout
        stdout.write(text)
        stdout.flush()

    def _err(self, text: str) -> None:
        out = self._out or sys.stderr
        out.write(text)
        out.flush()
