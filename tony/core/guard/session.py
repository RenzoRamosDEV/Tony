import asyncio
import math
import time
from collections.abc import Callable
from typing import NamedTuple, Protocol

from tony.core.events.core_events import AuthReason, AuthState
from tony.core.guard.policy import Auth

FREE_ATTEMPTS = 2
BACKOFF_S = (10, 30, 60)


class AuthStatus(NamedTuple):
    state: AuthState
    reason: AuthReason
    retry_in_s: int


class PinVerifier(Protocol):
    def has_valid_lock(self) -> bool: ...

    def verify(self, pin: str) -> bool: ...


def wait_after(failures: int) -> int:
    if failures <= FREE_ATTEMPTS:
        return 0
    return BACKOFF_S[min(failures - FREE_ATTEMPTS, len(BACKOFF_S)) - 1]


class EdithSession:
    """Edith's lock state: PIN attempts with back-off, conversation-only mode and idle relock."""

    def __init__(
        self,
        auth: Auth,
        pins: PinVerifier,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._auth = auth
        self._pins = pins
        self._monotonic = monotonic
        self._failures = 0
        self._retry_at = 0.0
        self._last_message: float | None = None
        self.conversation_only = False
        if not auth.pin_required:
            self.status = AuthStatus("unlocked", "not_required", 0)
        elif not pins.has_valid_lock():
            self._lock_conversation_only("no_lock_file")
        else:
            self.status = AuthStatus("locked", "start", 0)

    @property
    def unlocked(self) -> bool:
        return self.status.state == "unlocked"

    def attempt(self, pin: str) -> AuthStatus:
        if self.unlocked:
            return self.status
        if not self._pins.has_valid_lock():
            return self._lock_conversation_only("no_lock_file")
        remaining = self._retry_at - self._monotonic()
        if remaining > 0:
            return AuthStatus("locked", "backoff", math.ceil(remaining))
        if self._pins.verify(pin):
            self._failures = 0
            self.conversation_only = False
            self.status = AuthStatus("unlocked", "unlocked", 0)
            return self.status
        self._failures += 1
        wait = wait_after(self._failures)
        self._retry_at = self._monotonic() + wait
        self.status = AuthStatus("locked", "wrong_pin", wait)
        return self.status

    def cancel(self) -> AuthStatus:
        return self._lock_conversation_only("cancelled")

    def touch(self) -> AuthStatus | None:
        """Record a user message; relock and return the new status after an idle period."""
        now = self._monotonic()
        previous, self._last_message = self._last_message, now
        idle = previous is not None and now - previous >= self._auth.lock_after_min * 60
        if not (idle and self._auth.pin_required and self.unlocked):
            return None
        self.status = AuthStatus("locked", "idle", 0)
        return self.status

    def _lock_conversation_only(self, reason: AuthReason) -> AuthStatus:
        self.conversation_only = True
        self.status = AuthStatus("locked", reason, 0)
        return self.status


class PinPrompt(Protocol):
    async def request(self, status: AuthStatus) -> str | None:
        """Show the status and return the entered PIN, or None when the user cancels."""
        ...


class SessionGate:
    """Makes sure the session is unlocked before a delegated task, asking for the PIN if needed."""

    def __init__(
        self,
        session: EdithSession,
        prompt: PinPrompt,
        *,
        timeout_s: float,
        on_change: Callable[[AuthStatus], None] = lambda status: None,
    ) -> None:
        self.session = session
        self._prompt = prompt
        self._timeout_s = timeout_s
        self._on_change = on_change

    async def ensure_unlocked(self) -> bool:
        if self.session.unlocked:
            return True
        if self.session.conversation_only:
            return False
        try:
            async with asyncio.timeout(self._timeout_s):
                return await self._ask_until_unlocked()
        except TimeoutError:
            return False

    async def _ask_until_unlocked(self) -> bool:
        while True:
            pin = await self._prompt.request(self.session.status)
            if pin is None:
                self._on_change(self.session.cancel())
                return False
            if self.session.attempt(pin).state == "unlocked":
                self._on_change(self.session.status)
                return True
