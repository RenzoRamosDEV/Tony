import asyncio
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, TextIO, runtime_checkable

YES = frozenset({"s", "si", "sí", "y", "yes"})


@runtime_checkable
class Confirmer(Protocol):
    async def ask(self, question: str) -> bool | None: ...


class NoChannelConfirmer:
    async def ask(self, question: str) -> bool | None:
        return False


class CliConfirmer:
    """Asks on stderr and reads one stdin line; only an explicit yes confirms."""

    def __init__(
        self,
        readline: Callable[[], str | None] = sys.stdin.readline,
        err: TextIO | None = None,
    ) -> None:
        self._readline = readline
        self._err = err

    async def ask(self, question: str) -> bool | None:
        err = self._err or sys.stderr
        err.write(f"{question} ")
        err.flush()
        line = await self._read_line()
        return (line or "").strip().casefold() in YES

    def _read_line(self) -> asyncio.Future[str | None]:
        # A daemon thread, unlike asyncio.to_thread, never blocks interpreter exit when
        # nobody answers before the confirmation timeout.
        loop = asyncio.get_running_loop()
        answer: asyncio.Future[str | None] = loop.create_future()

        def read() -> None:
            line = self._readline()
            # The loop may already be closed when a late answer arrives after a timeout.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(_resolve, answer, line)

        threading.Thread(target=read, daemon=True).start()
        return answer


def _resolve(answer: asyncio.Future[str | None], line: str | None) -> None:
    if not answer.done():
        answer.set_result(line)
