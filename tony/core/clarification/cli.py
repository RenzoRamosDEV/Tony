import sys
from typing import TextIO

from tony.core.clarification.request import ClarificationRequest
from tony.core.guard.confirm import LineReader


def parse_answer(line: str | None, options: list[str]) -> str | None:
    """A blank line is no answer; a number within the options picks that option."""
    text = (line or "").strip()
    if not text:
        return None
    if text.isascii() and text.isdigit() and 1 <= int(text) <= len(options):
        return options[int(text) - 1]
    return text


class CliClarifier:
    """Asks on stderr and reads one line, so stdout stays clean for results."""

    def __init__(self, read_line: LineReader, *, err: TextIO | None = None) -> None:
        self._read_line = read_line
        self._err = err

    async def ask(self, request: ClarificationRequest) -> str | None:
        err = self._err or sys.stderr
        err.write(f"{request.agent.title()}: {request.question}\n")
        for number, option in enumerate(request.options, start=1):
            err.write(f"{number}) {option}\n")
        err.flush()
        return parse_answer(await self._read_line(), request.options)
