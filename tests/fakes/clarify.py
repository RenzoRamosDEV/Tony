import asyncio

from tests.fakes.confirm import HANG
from tony.core.clarification.request import ClarificationRequest

__all__ = ["HANG", "FakeClarifier"]


class FakeClarifier:
    """Clarifier answering from a script; `HANG` never answers, `None` means no answer."""

    def __init__(
        self, answers: list | None = None, *, delay: float = 0.0, error: Exception | None = None
    ) -> None:
        self._answers = list(answers or [])
        self._delay = delay
        self._error = error
        self.requests: list[ClarificationRequest] = []
        self.cancelled = False

    @property
    def questions(self) -> list[str]:
        return [request.question for request in self.requests]

    async def ask(self, request: ClarificationRequest) -> str | None:
        self.requests.append(request)
        if self._error:
            raise self._error
        answer = self._answers.pop(0) if self._answers else None
        try:
            if answer is HANG:
                await asyncio.Event().wait()
            if self._delay:
                await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return answer
