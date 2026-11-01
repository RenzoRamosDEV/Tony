from collections.abc import Callable
from typing import Any


class PynputHotkeys:
    """pynput global hotkeys (X11 only); callbacks run on pynput's listener thread."""

    def __init__(self, mapping: dict[str, Callable[[], None]]) -> None:
        from pynput.keyboard import GlobalHotKeys

        self._listener: Any = GlobalHotKeys(mapping)

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()
