from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from tony.apps.desktop.presenters.pin import PinPresenter


class PinDialog(QDialog):
    """Modal PIN entry with hidden input, back-off countdown and cancel."""

    def __init__(self, presenter: PinPresenter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self.setWindowTitle("Edith")
        self.setModal(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.countdown = QLabel()
        self.cancel_button = QPushButton("Cancelar")
        # Enter in the PIN field must submit it, not trigger the dialog's default button.
        self.cancel_button.setAutoDefault(False)
        layout = QVBoxLayout(self)
        for widget in (self.message, self.field, self.countdown, self.cancel_button):
            layout.addWidget(widget)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(presenter.tick)
        self.field.returnPressed.connect(self._submit)
        self.cancel_button.clicked.connect(presenter.cancel)
        self.rejected.connect(self._closed_by_user)
        presenter.subscribe(self.render)

    def _submit(self) -> None:
        self._presenter.submit(self.field.text())
        self.field.clear()

    def _closed_by_user(self) -> None:
        if self._presenter.mode != "hidden":
            self._presenter.cancel()

    def render(self) -> None:
        presenter = self._presenter
        if presenter.mode == "hidden":
            self._timer.stop()
            self.hide()
            return
        self.message.setText(presenter.message)
        prompting = presenter.mode == "prompt"
        self.field.setVisible(prompting)
        self.field.setEnabled(presenter.input_enabled)
        remaining = presenter.remaining_s
        self.countdown.setVisible(prompting and remaining > 0)
        self.countdown.setText(f"Podrá intentarlo de nuevo en {remaining} s")
        if remaining > 0:
            self._timer.start()
        else:
            self._timer.stop()
        if not self.isVisible():
            self.open()
