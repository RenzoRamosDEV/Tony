from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tony.apps.desktop.presenters.markdown import MarkdownRenderer
from tony.apps.desktop.presenters.observable import Observable
from tony.core.events.core_events import Event, ReplyMode

Submit = Callable[[dict[str, Any]], None]

AGENT_COLOURS = {"jarvis": "#2F6FED", "viernes": "#2E9E5B", "edith": "#E0A100"}
NEUTRAL = "#6B7280"
USER = "user"
SYSTEM = "system"


@dataclass
class Bubble:
    agent: str
    label: str
    colour: str
    markdown: str
    html: str
    open: bool


class ChatPresenter(Observable):
    """Chat zone state: one bubble per message, agent replies growing token by token."""

    def __init__(self, submit: Submit, renderer: MarkdownRenderer | None = None) -> None:
        super().__init__()
        self._submit = submit
        self._renderer = renderer or MarkdownRenderer()
        self.bubbles: list[Bubble] = []
        self.mode: ReplyMode = "auto"

    def send(self, text: str) -> None:
        if not text.strip():
            return
        self._add(USER, "Tú", text)
        self._submit({"type": "send_message", "text": text})

    def select_mode(self, mode: ReplyMode) -> None:
        if mode != self.mode:
            self._submit({"type": "set_mode", "mode": mode})

    def apply(self, event: Event) -> None:
        kind = event["type"]
        if kind == "token":
            self._grow(event["agent"], event["text"])
        elif kind == "result" and event["scope"] == "turn":
            self._finish_turn(event["agent"], event["text"])
        elif kind == "progress":
            self._add(event["agent"], event["agent"].title(), event["text"])
        elif kind == "error":
            self._add(SYSTEM, "Tony", f"Error ({event['source']}): {event['message']}")
        elif kind == "reply_mode":
            self.mode = event["mode"]
            self._changed()

    def _grow(self, agent: str, text: str) -> None:
        last = self.bubbles[-1] if self.bubbles else None
        if last is None or not last.open or last.agent != agent:
            self._close()
            last = self._bubble(agent, agent.title(), "", is_open=True)
            self.bubbles.append(last)
        last.markdown += text
        last.html = self._renderer.render(last.markdown)
        self._changed()

    def _finish_turn(self, agent: str, text: str) -> None:
        if self.bubbles and self.bubbles[-1].open:
            self._close()
            self._changed()
        elif text:
            self._add(agent, agent.title(), text)

    def _add(self, agent: str, label: str, text: str) -> None:
        self._close()
        self.bubbles.append(self._bubble(agent, label, text, is_open=False))
        self._changed()

    def _close(self) -> None:
        for bubble in self.bubbles:
            bubble.open = False

    def _bubble(self, agent: str, label: str, text: str, *, is_open: bool) -> Bubble:
        return Bubble(
            agent=agent,
            label=label,
            colour=AGENT_COLOURS.get(agent, NEUTRAL),
            markdown=text,
            html=self._renderer.render(text),
            open=is_open,
        )
