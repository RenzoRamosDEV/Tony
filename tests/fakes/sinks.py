"""In-memory EventSink."""

from __future__ import annotations

from typing import Any


class ListEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]

    def payloads(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.events if kind == event_type]
