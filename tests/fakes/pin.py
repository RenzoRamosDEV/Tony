import asyncio

HANG = object()


class FakePinPrompt:
    """PinPrompt answering from a script; None cancels, `HANG` never answers."""

    def __init__(self, answers: list | None = None) -> None:
        self._answers = list(answers or [])
        self.shown: list = []

    async def request(self, status) -> str | None:
        self.shown.append(status)
        answer = self._answers.pop(0) if self._answers else None
        if answer is HANG:
            await asyncio.Event().wait()
        return answer
