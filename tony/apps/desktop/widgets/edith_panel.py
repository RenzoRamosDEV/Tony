from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tony.apps.desktop.presenters.edith import EdithPresenter

ALL = "todos"
FILTERS = (ALL, "allow", "confirm", "deny")
AUDIT_HEADERS = ("hora", "agente", "tool", "veredicto", "regla", "decisión")


class EdithPanel(QWidget):
    """Pending-confirmation banner and today's audit with a verdict filter."""

    def __init__(self, presenter: EdithPresenter) -> None:
        super().__init__()
        self._presenter = presenter
        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.question = QLabel()
        self.question.setWordWrap(True)
        self.allow_button = QPushButton("Permitir")
        self.deny_button = QPushButton("Denegar")
        self.always_button = QPushButton("Permitir siempre")
        buttons = QHBoxLayout()
        for button in (self.allow_button, self.deny_button, self.always_button):
            buttons.addWidget(button)
        banner_layout = QVBoxLayout(self.banner)
        banner_layout.addWidget(self.question)
        banner_layout.addLayout(buttons)
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.audit = QTableWidget(0, len(AUDIT_HEADERS))
        self.audit.setHorizontalHeaderLabels(AUDIT_HEADERS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.banner)
        layout.addWidget(self.filter)
        layout.addWidget(self.audit)
        self.allow_button.clicked.connect(presenter.allow)
        self.deny_button.clicked.connect(presenter.deny)
        self.always_button.clicked.connect(presenter.allow_always)
        self.filter.currentTextChanged.connect(self._filter_changed)
        presenter.subscribe(self.render)
        self.render()

    def _filter_changed(self, text: str) -> None:
        self._presenter.set_filter(None if text == ALL else text)

    def render(self) -> None:
        pending = self._presenter.pending
        self.banner.setVisible(pending is not None)
        if pending is not None:
            self.question.setText(pending.question)
            self.always_button.setVisible(pending.offers_always)
        rows = self._presenter.rows
        self.audit.setRowCount(len(rows))
        for index, row in enumerate(rows):
            cells = (row.time, row.agent, row.tool, row.verdict, row.rule, row.user_decision or "-")
            for column, text in enumerate(cells):
                self.audit.setItem(index, column, QTableWidgetItem(text))
