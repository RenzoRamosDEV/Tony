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
