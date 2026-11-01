from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tony.apps.desktop.presenters.activity import ActivityPresenter, ToolNode


class ActivityPanel(QWidget):
    """Delegated tasks as a tree (tool calls, subagents) and the MCP servers list."""

    def __init__(self, presenter: ActivityPresenter) -> None:
        super().__init__()
        self._presenter = presenter
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tarea", "Estado"])
        self.servers = QListWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree, stretch=3)
        layout.addWidget(self.servers, stretch=1)
        presenter.subscribe(self.render)

    def render(self) -> None:
        self.tree.clear()
        for task in self._presenter.tasks:
            node = QTreeWidgetItem([task.label, task.summary])
            _add_calls(node, task.calls)
            for subagent in task.subagents:
                child = QTreeWidgetItem([subagent.name, ""])
                _add_calls(child, subagent.calls)
                node.addChild(child)
            self.tree.addTopLevelItem(node)
            node.setExpanded(True)
        self.servers.clear()
        for row in self._presenter.servers:
            item = QListWidgetItem(row.label)
            if row.colour:
                item.setForeground(QBrush(QColor(row.colour)))
            self.servers.addItem(item)


def _add_calls(parent: QTreeWidgetItem, calls: list[ToolNode]) -> None:
    for call in calls:
        parent.addChild(QTreeWidgetItem([call.label, ""]))
