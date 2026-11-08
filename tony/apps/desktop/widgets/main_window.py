from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QWidget

from tony.apps.desktop.page_bridge import PageBridge
from tony.apps.desktop.presenters.tray import TrayPresenter
from tony.core.events.core_events import Event


class MainWindow(QMainWindow):
    """One window whose content is the web front (or the missing-build message)."""

    dispatched = Signal(object)

    def __init__(
        self,
        tray_presenter: TrayPresenter,
        bridge: PageBridge,
        content: QWidget,
        on_close: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__()
        self.tray_presenter = tray_presenter
        self.bridge = bridge
        self._on_close = on_close
        self.setWindowTitle("Tony")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1100, 720)
        self.setCentralWidget(content)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        self._on_close()
        super().closeEvent(event)

    def reveal(self, confirmation: bool = False) -> None:
        """Show, restore and raise the window; on a confirmation, the page focuses «Denegar»."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if confirmation:
            self.centralWidget().setFocus()
            self.bridge.focusConfirmation.emit()

    def dispatch(self, event: Event) -> None:
        self.bridge.publish(event)
        self.report(event)

    def report(self, event: Event) -> None:
        """An event the page already has: only the tray and notifications still need it."""
        self.tray_presenter.apply(event)
        self.dispatched.emit(event)
