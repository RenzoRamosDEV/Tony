"""ConfirmGate double that always answers the same and records requests."""

from __future__ import annotations

from tony.core.mcp import ConfirmRequest


class AutoConfirmGate:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.requests: list[ConfirmRequest] = []

    async def confirm(self, request: ConfirmRequest) -> bool:
        self.requests.append(request)
        return self.answer
