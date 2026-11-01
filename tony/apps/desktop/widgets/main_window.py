from collections.abc import Callable

from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tony.apps.desktop.presenters.bundle import Presenters
from tony.apps.desktop.widgets.activity_panel import ActivityPanel
from tony.apps.desktop.widgets.chat_view import ChatView
from tony.apps.desktop.widgets.edith_panel import EdithPanel
from tony.apps.desktop.widgets.pin_dialog import PinDialog
from tony.core.events.core_events import Event
from tony.core.memory.preferences import REPLY_MODES

__all__ = ["MainWindow", "Presenters"]


class MainWindow(QMainWindow):
    """One window: Chat, plus collapsible Activity and Edith zones."""

    def __init__(self, presenters: Presenters, on_close: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.presenters = presenters
        self._on_close = on_close
        self.setWindowTitle("Tony")
        self.resize(1100, 720)
        self.chat_view = ChatView(presenters.chat)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escriba un mensaje y pulse Intro")
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(REPLY_MODES)
        self.microphone = QPushButton("Micrófono")
        self.microphone.setEnabled(False)
        self.microphone.setToolTip("La entrada por voz aún no está disponible.")
        self.activity_panel = ActivityPanel(presenters.activity)
        self.edith_panel = EdithPanel(presenters.edith)
        self.activity_zone = _collapsible("Actividad", self.activity_panel)
        self.edith_zone = _collapsible("Edith", self.edith_panel)
        self.pin_dialog = PinDialog(presenters.pin, self)
        self.unlock_action = QAction("Desbloquear Edith", self)
        self.unlock_action.setEnabled(False)
        self.menuBar().addAction(self.unlock_action)
        self.setCentralWidget(self._layout())
        self.input.returnPressed.connect(self._send)
        self.mode_selector.currentTextChanged.connect(presenters.chat.select_mode)
        self.unlock_action.triggered.connect(presenters.pin.request_unlock)
        presenters.chat.subscribe(self._render_mode)
        presenters.pin.subscribe(self._render_unlock)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        self._on_close()
        super().closeEvent(event)

    def dispatch(self, event: Event) -> None:
        self.presenters.apply(event)

    def _send(self) -> None:
        self.presenters.chat.send(self.input.text())
        self.input.clear()

    def _render_mode(self) -> None:
        self.mode_selector.blockSignals(True)
        self.mode_selector.setCurrentText(self.presenters.chat.mode)
        self.mode_selector.blockSignals(False)

    def _render_unlock(self) -> None:
        self.unlock_action.setEnabled(self.presenters.pin.can_unlock)

    def _layout(self) -> QWidget:
        controls = QHBoxLayout()
        controls.addWidget(self.input, stretch=1)
        controls.addWidget(self.mode_selector)
        controls.addWidget(self.microphone)
        chat = QWidget()
        chat_layout = QVBoxLayout(chat)
        chat_layout.addWidget(self.chat_view)
        chat_layout.addLayout(controls)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(self.activity_zone)
        side_layout.addWidget(self.edith_zone)
        splitter = QSplitter()
        splitter.addWidget(chat)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return splitter


def _collapsible(title: str, content: QWidget) -> QGroupBox:
    zone = QGroupBox(title)
    zone.setCheckable(True)
    zone.setChecked(True)
    layout = QVBoxLayout(zone)
    layout.addWidget(content)
    zone.toggled.connect(content.setVisible)
    return zone
