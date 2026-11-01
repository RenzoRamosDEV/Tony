from typing import Any


class ListEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [event["type"] for event in self.events]
