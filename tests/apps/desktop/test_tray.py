from PySide6.QtWidgets import QMainWindow

from tony.apps.desktop.presenters.tray import TrayPresenter
from tony.apps.desktop.system.tray import create_tray
from tony.core.events import core_events as ev


def make(qtbot, *, available=True, enabled=True):
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    presenter = TrayPresenter()
    quits = []
    tray = create_tray(
        window,
        presenter,
        enabled=enabled,
        available=lambda: available,
        quit=lambda: quits.append(1),
    )
    return window, presenter, tray, quits


def test_tray_has_show_hide_and_quit(qtbot):
    _, _, tray, _ = make(qtbot)
    assert [action.text() for action in tray.contextMenu().actions()] == [
        "Mostrar/Ocultar",
        "Salir",
    ]
    assert tray.toolTip() == "Tony — en espera"
    tray.hide()


def test_show_hide_toggles_the_window(qtbot):
    window, _, tray, _ = make(qtbot)
    toggle = tray.contextMenu().actions()[0]
    toggle.trigger()
    assert not window.isVisible()
    toggle.trigger()
    assert window.isVisible()
    tray.hide()


def test_quit_action_quits(qtbot):
    _, _, tray, quits = make(qtbot)
    tray.contextMenu().actions()[1].trigger()
    assert quits == [1]
    tray.hide()


def test_tray_follows_the_presenter(qtbot):
    _, presenter, tray, _ = make(qtbot)
    presenter.apply(ev.needs_confirmation("t1", "x", "{}", "¿Autoriza?", True))
    assert tray.toolTip() == "Tony — esperando confirmación"
    assert tray.icon().pixmap(16, 16).toImage().pixelColor(8, 8).name() == "#e0a100"
    tray.hide()


def test_no_tray_when_unavailable_or_disabled(qtbot):
    assert make(qtbot, available=False)[2] is None
    assert make(qtbot, enabled=False)[2] is None
