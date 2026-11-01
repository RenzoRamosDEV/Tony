from html import escape

from PySide6.QtWidgets import QTextBrowser

from tony.apps.desktop.presenters.chat import ChatPresenter


class ChatView(QTextBrowser):
    """Renders the chat presenter's bubbles: a coloured label and the Markdown HTML."""

    def __init__(self, presenter: ChatPresenter) -> None:
        super().__init__()
        self._presenter = presenter
        self.setOpenExternalLinks(True)
        presenter.subscribe(self.render)
        self.html = ""

    @property
    def bubble_count(self) -> int:
        return len(self._presenter.bubbles)

    def render(self) -> None:
        self.html = "".join(
            f'<div style="margin:6px 0; border-left:4px solid {bubble.colour}; padding-left:8px">'
            f'<b style="color:{bubble.colour}">{escape(bubble.label)}</b>{bubble.html}</div>'
            for bubble in self._presenter.bubbles
        )
        self.setHtml(self.html)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
