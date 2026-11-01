from collections.abc import Callable

Listener = Callable[[], None]


class Observable:
    """Presenter base: widgets subscribe and re-render on every change."""

    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in self._listeners:
            listener()
