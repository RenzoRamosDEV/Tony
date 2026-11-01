from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMainWindow, QMenu, QSystemTrayIcon

from tony.apps.desktop.presenters.tray import TrayPresenter

ICON_SIZE = 64


def create_tray(
    window: QMainWindow,
    presenter: TrayPresenter,
    *,
    enabled: bool,
    quit: Callable[[], None],
    available: Callable[[], bool] = QSystemTrayIcon.isSystemTrayAvailable,
) -> QSystemTrayIcon | None:
    """The tray icon with «Mostrar/Ocultar» and «Salir», or None without a system tray."""
    if not enabled or not available():
        return None
    tray = QSystemTrayIcon(window)
    menu = QMenu(window)
    toggle = QAction("Mostrar/Ocultar", menu)
    toggle.triggered.connect(lambda: window.setVisible(not window.isVisible()))
    leave = QAction("Salir", menu)
    leave.triggered.connect(quit)
    menu.addActions([toggle, leave])
    tray.setContextMenu(menu)

    def render() -> None:
        tray.setToolTip(presenter.tooltip)
        tray.setIcon(_dot(presenter.colour))

    presenter.subscribe(render)
    render()
    tray.show()
    return tray


def _dot(colour: str) -> QIcon:
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, ICON_SIZE, ICON_SIZE)
    painter.end()
    return QIcon(pixmap)
