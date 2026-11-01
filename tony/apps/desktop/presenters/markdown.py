from markdown_it import MarkdownIt


class MarkdownRenderer:
    """CommonMark plus tables, with raw HTML escaped."""

    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark", {"html": False}).enable("table")

    def render(self, text: str) -> str:
        return self._markdown.render(text)
