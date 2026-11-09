import asyncio
import sys
import threading
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import datetime
from typing import Protocol, TextIO, runtime_checkable

from pydantic import BaseModel

YES = frozenset({"s", "si", "sí", "y", "yes"})


class ConfirmationRequest(BaseModel):
    task_id: str
    tool: str
    args_preview: str
    question: str
    allow_always: bool = False
    approval_id: str | None = None
    args_digest: str | None = None
    policy_version: str | None = None
    expires_at: datetime | None = None
    preview: dict[str, str | int] = {}


@runtime_checkable
class Confirmer(Protocol):
    async def ask(self, request: ConfirmationRequest) -> bool | None: ...


class NoChannelConfirmer:
    async def ask(self, request: ConfirmationRequest) -> bool | None:
        return False


LineReader = Callable[[], Awaitable[str | None]]


class CliConfirmer:
    """Asks on stderr and reads one line; only an explicit yes confirms."""

    def __init__(
        self,
        read_line: LineReader | None = None,
        *,
        prefix: str = "",
        err: TextIO | None = None,
    ) -> None:
        self._read_line = read_line or thread_line_reader(sys.stdin.readline)
        self._prefix = prefix
        self._err = err

    async def ask(self, request: ConfirmationRequest) -> bool | None:
        err = self._err or sys.stderr
        for name, value in request.preview.items():
            err.write(f"{name}: {value}\n")
        err.write(f"{self._prefix}{request.question} ")
        err.flush()
        line = await self._read_line()
        return (line or "").strip().casefold() in YES


def thread_line_reader(readline: Callable[[], str | None]) -> LineReader:
    """One daemon thread per read: unlike asyncio.to_thread, it never blocks interpreter exit
    when nobody answers before the confirmation timeout."""

    def read_line() -> asyncio.Future[str | None]:
        loop = asyncio.get_running_loop()
        answer: asyncio.Future[str | None] = loop.create_future()

        def read() -> None:
            line = readline()
            # The loop may already be closed when a late answer arrives after a timeout.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(_resolve, answer, line)

        threading.Thread(target=read, daemon=True).start()
        return answer

    return read_line


def _resolve(answer: asyncio.Future[str | None], line: str | None) -> None:
    if not answer.done():
        answer.set_result(line)


class ConsoleLines:
    """Console input shared by the chat REPL and the confirmer through one queue.

    A single reader thread feeds the queue, so a read cancelled by a timeout leaves the next
    line queued for whoever reads after it.
    """

    def __init__(self, source: Iterable[str]) -> None:
        self._source = source
        self._queue: asyncio.Queue[str | None] | None = None

    async def next(self) -> str | None:
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._start(asyncio.get_running_loop(), self._queue)
        line = await self._queue.get()
        if line is None:
            self._queue.put_nowait(None)
            return None
        return line.rstrip("\n")

    def _start(self, loop: asyncio.AbstractEventLoop, lines: "asyncio.Queue[str | None]") -> None:
        def pump() -> None:
            with suppress(RuntimeError):
                for line in self._source:
                    loop.call_soon_threadsafe(lines.put_nowait, line)
                loop.call_soon_threadsafe(lines.put_nowait, None)

        threading.Thread(target=pump, daemon=True).start()
