"""Interactive [s/N] confirmation on the terminal."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from tony.core.mcp import ConfirmRequest

AFFIRMATIVE = {"s", "si", "sí"}


class CliConfirmGate:
    def __init__(
        self, agent_name: str, timeout_s: float, reader: Callable[[str], str] = input
    ) -> None:
        self._agent_name = agent_name
        self._timeout_s = timeout_s
        self._reader = reader

    async def confirm(self, request: ConfirmRequest) -> bool:
        prompt = (
            f"{self._agent_name} quiere ejecutar {request.tool} con {request.args_normalized}. "
            "¿Confirmas? [s/N] "
        )
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(self._reader, prompt), self._timeout_s
            )
        except TimeoutError:
            return False
        return answer.strip().lower() in AFFIRMATIVE
