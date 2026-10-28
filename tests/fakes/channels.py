"""Channel double that keeps every message in memory."""

from __future__ import annotations

from tony.core.channels.ports import ChannelMessage


class ListChannel:
    def __init__(self) -> None:
        self.messages: list[ChannelMessage] = []

    async def send(self, message: ChannelMessage) -> None:
        self.messages.append(message)

    def of_type[T](self, kind: type[T]) -> list[T]:
        return [m for m in self.messages if isinstance(m, kind)]
