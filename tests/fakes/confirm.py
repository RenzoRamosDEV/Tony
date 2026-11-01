import asyncio

HANG = object()


class FakeConfirmer:
    """Confirmer answering from a script; `HANG` never answers."""

    def __init__(self, answers: list | None = None) -> None:
        self._answers = list(answers or [])
        self.questions: list[str] = []

    async def ask(self, question: str) -> bool | None:
        self.questions.append(question)
        answer = self._answers.pop(0) if self._answers else False
        if answer is HANG:
            await asyncio.Event().wait()
        return answer


class FakeWording:
    """QuestionWording returning scripted text, raising, or answering late."""

    def __init__(
        self, text: str = "", *, error: Exception | None = None, delay: float = 0.0
    ) -> None:
        self._text = text
        self._error = error
        self._delay = delay
        self.inputs: list[tuple[str, str, str]] = []

    async def word(self, tool: str, preview: str, rule: str) -> str:
        self.inputs.append((tool, preview, rule))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._text
