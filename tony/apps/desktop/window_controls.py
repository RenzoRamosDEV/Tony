from typing import Protocol

from PySide6.QtCore import QObject, Qt, Slot

_EDGES = {
    "top": Qt.Edge.TopEdge,
    "bottom": Qt.Edge.BottomEdge,
    "left": Qt.Edge.LeftEdge,
    "right": Qt.Edge.RightEdge,
    "top-left": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    "top-right": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    "bottom-left": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    "bottom-right": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
}


class _WindowHandle(Protocol):
    def startSystemMove(self) -> bool: ...  # noqa: N802 (Qt API)
    def startSystemResize(self, edges: Qt.Edge) -> bool: ...  # noqa: N802 (Qt API)


class _Window(Protocol):
    def showMinimized(self) -> None: ...  # noqa: N802 (Qt API)
    def showMaximized(self) -> None: ...  # noqa: N802 (Qt API)
    def showNormal(self) -> None: ...  # noqa: N802 (Qt API)
    def isMaximized(self) -> bool: ...  # noqa: N802 (Qt API)
    def close(self) -> None: ...
    def windowHandle(self) -> _WindowHandle | None: ...  # noqa: N802 (Qt API)


class WindowControls(QObject):
    """The custom titlebar's handle on its own window, exposed as `windowControls` over
    QWebChannel: the OS no longer draws a titlebar, so the page asks for move/resize/
    minimize/maximize/close directly."""

    def __init__(self, window: _Window, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window

    @Slot()
    def minimize(self) -> None:
        self._window.showMinimized()

    @Slot()
    def toggleMaximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @Slot()
    def close(self) -> None:
        self._window.close()

    @Slot()
    def startMove(self) -> None:
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    @Slot(str)
    def startResize(self, edge: str) -> None:
        handle = self._window.windowHandle()
        value = _EDGES.get(edge)
        if handle is not None and value is not None:
            handle.startSystemResize(value)

    @Slot(result=bool)
    def isMaximized(self) -> bool:
        return self._window.isMaximized()
