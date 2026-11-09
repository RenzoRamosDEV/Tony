from typing import Protocol, runtime_checkable

from tony.core.clarification.request import ClarificationRequest


@runtime_checkable
class Clarifier(Protocol):
    async def ask(self, request: ClarificationRequest) -> str | None:
        """The user's answer, or None when nobody answered."""
        ...


class NoChannelClarifier:
    async def ask(self, request: ClarificationRequest) -> str | None:
        return None
