"""Interactive [s/N] confirmation on the terminal."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from tony.apps.cli.stdin_reader import LineSource, StdinReader
from tony.core.mcp import ConfirmRequest

AFFIRMATIVE = {"s", "si", "sí"}
StdinLines = StdinReader


class CliConfirmGate:
    def __init__(
        self,
        agent_name: str,
        timeout_s: float,
        lines: LineSource | None = None,
        out: TextIO | None = None,
    ) -> None:
        self._agent_name = agent_name
        self._timeout_s = timeout_s
        self._lines = lines or StdinReader()
        self._out = out
        self._lock = asyncio.Lock()

    async def confirm(self, request: ConfirmRequest) -> bool:
        async with self._lock:
            self._write(
                f"{self._agent_name} quiere ejecutar {request.tool} con "
                f"{request.args_normalized}. ¿Confirmas? [s/N] "
            )
            try:
                answer = await asyncio.wait_for(self._lines.readline(), self._timeout_s)
            except TimeoutError:
                self._write(f"\nSin respuesta en {self._timeout_s:g} s; se rechaza.\n")
                return False
        return answer is not None and answer.strip().lower() in AFFIRMATIVE

    def _write(self, text: str) -> None:
        out = self._out or sys.stderr
        out.write(text)
        out.flush()
