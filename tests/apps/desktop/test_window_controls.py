from PySide6.QtCore import Qt

from tony.apps.desktop.window_controls import WindowControls


class FakeHandle:
    def __init__(self) -> None:
        self.moved = False
        self.resized_with: Qt.Edge | None = None

    def startSystemMove(self) -> bool:
        self.moved = True
        return True

    def startSystemResize(self, edges: Qt.Edge) -> bool:
        self.resized_with = edges
        return True


class FakeWindow:
    def __init__(self, *, handle: FakeHandle | None = None, maximized: bool = False) -> None:
        self.handle = handle
        self.maximized = maximized
        self.minimized = False
        self.closed = False

    def showMinimized(self) -> None:
        self.minimized = True

    def showMaximized(self) -> None:
        self.maximized = True

    def showNormal(self) -> None:
        self.maximized = False

    def isMaximized(self) -> bool:
        return self.maximized

    def close(self) -> None:
        self.closed = True

    def windowHandle(self):
        return self.handle


def test_minimize_minimizes_the_window():
    window = FakeWindow()
    WindowControls(window).minimize()
    assert window.minimized is True


def test_toggle_maximize_maximizes_a_normal_window():
    window = FakeWindow(maximized=False)
    WindowControls(window).toggleMaximize()
    assert window.maximized is True


def test_toggle_maximize_restores_a_maximized_window():
    window = FakeWindow(maximized=True)
    WindowControls(window).toggleMaximize()
    assert window.maximized is False


def test_close_closes_the_window():
    window = FakeWindow()
    WindowControls(window).close()
    assert window.closed is True


def test_start_move_asks_the_window_handle_to_move():
    handle = FakeHandle()
    window = FakeWindow(handle=handle)
    WindowControls(window).startMove()
    assert handle.moved is True


def test_start_move_without_a_window_handle_does_nothing():
    window = FakeWindow(handle=None)
    WindowControls(window).startMove()  # must not raise


def test_start_resize_asks_the_window_handle_to_resize_with_the_matching_edge():
    handle = FakeHandle()
    window = FakeWindow(handle=handle)
    WindowControls(window).startResize("bottom-right")
    assert handle.resized_with == Qt.Edge.BottomEdge | Qt.Edge.RightEdge


def test_start_resize_with_an_unknown_edge_does_nothing():
    handle = FakeHandle()
    window = FakeWindow(handle=handle)
    WindowControls(window).startResize("not-an-edge")
    assert handle.resized_with is None


def test_is_maximized_reflects_the_window_state():
    assert WindowControls(FakeWindow(maximized=True)).isMaximized() is True
    assert WindowControls(FakeWindow(maximized=False)).isMaximized() is False
