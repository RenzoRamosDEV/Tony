"""Desktop OS doubles: global hotkeys and native notifications."""

from collections.abc import Callable


class FakeHotkeys:
    """Records the registered combinations; `press(combo)` runs its callback."""

    instances: list["FakeHotkeys"] = []

    def __init__(self, mapping: dict[str, Callable[[], None]]) -> None:
        self.mapping = mapping
        self.started = False
        self.stopped = False
        FakeHotkeys.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def press(self, combo: str) -> None:
        self.mapping[combo]()


class FakeNotifier:
    """Records notifications; `click()` runs the last one's callback; `error` makes it raise."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.shown: list[tuple[str, str]] = []
        self._on_click: Callable[[], None] | None = None

    def notify(self, title: str, body: str, on_click: Callable[[], None]) -> None:
        if self.error is not None:
            raise self.error
        self.shown.append((title, body))
        self._on_click = on_click

    def click(self) -> None:
        assert self._on_click is not None
        self._on_click()

    def close(self) -> None:
        return None
