import os

from PySide6.QtWidgets import QWidget


def test_qt_runs_headless(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)

    widget.show()

    assert widget.isVisible()
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
