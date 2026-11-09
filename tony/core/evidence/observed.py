class ObservedTexts:
    """Append-only record of the tool result texts a task has seen."""

    def __init__(self) -> None:
        self._texts: list[str] = []

    def add(self, text: str) -> None:
        self._texts.append(text)

    def texts(self) -> tuple[str, ...]:
        return tuple(self._texts)
