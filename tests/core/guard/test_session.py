import pytest

from tony.core.guard.policy import Auth
from tony.core.guard.session import AuthStatus, EdithSession, wait_after

PIN = "4821"


class FakePins:
    def __init__(self, valid_lock=True) -> None:
        self.valid_lock = valid_lock
        self.checked: list[str] = []

    def has_valid_lock(self) -> bool:
        return self.valid_lock

    def verify(self, pin: str) -> bool:
        self.checked.append(pin)
        return self.valid_lock and pin == PIN


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def session(pin_required=True, valid_lock=True, lock_after_min=30):
    clock, pins = Clock(), FakePins(valid_lock)
    edith = EdithSession(
        Auth(pin_required=pin_required, lock_after_min=lock_after_min), pins, monotonic=clock
    )
    return edith, clock, pins


@pytest.mark.parametrize(
    ("pin_required", "valid_lock", "status", "conversation_only"),
    [
        (False, False, AuthStatus("unlocked", "not_required", 0), False),
        (True, False, AuthStatus("locked", "no_lock_file", 0), True),
        (True, True, AuthStatus("locked", "start", 0), False),
    ],
)
def test_start_state(pin_required, valid_lock, status, conversation_only):
    edith, *_ = session(pin_required, valid_lock)

    assert edith.status == status
    assert edith.conversation_only is conversation_only
    assert edith.unlocked is (status.state == "unlocked")


@pytest.mark.parametrize(
    ("failures", "wait"), [(0, 0), (1, 0), (2, 0), (3, 10), (4, 30), (5, 60), (6, 60), (9, 60)]
)
def test_wait_after_failures(failures, wait):
    assert wait_after(failures) == wait


def test_back_off_sequence_when_retrying_as_soon_as_allowed():
    edith, clock, _ = session()
    waits = []

    for _ in range(6):
        status = edith.attempt("0000")
        waits.append(status.retry_in_s)
        assert (status.state, status.reason) == ("locked", "wrong_pin")
        clock.now += status.retry_in_s

    assert waits == [0, 0, 10, 30, 60, 60]


def test_attempt_during_the_wait_is_rejected_unchecked_and_not_counted():
    edith, clock, pins = session()
    for _ in range(3):
        edith.attempt("0000")
    clock.now += 4
    pins.checked.clear()

    status = edith.attempt(PIN)

    assert status == AuthStatus("locked", "backoff", 6)
    assert pins.checked == []
    clock.now += 6
    assert edith.attempt("0000").retry_in_s == 30


def test_remaining_wait_rounds_up_to_whole_seconds():
    edith, clock, _ = session()
    for _ in range(3):
        edith.attempt("0000")
    clock.now += 9.2

    assert edith.attempt(PIN) == AuthStatus("locked", "backoff", 1)


def test_wait_ends_exactly_at_the_boundary():
    edith, clock, _ = session()
    for _ in range(3):
        edith.attempt("0000")
    clock.now += 10

    assert edith.attempt(PIN) == AuthStatus("unlocked", "unlocked", 0)


def test_success_resets_the_failure_count():
    edith, clock, _ = session()
    edith.attempt("0000")
    edith.attempt("0000")

    assert edith.attempt(PIN) == AuthStatus("unlocked", "unlocked", 0)
    assert edith.unlocked
    edith.touch()
    clock.now += 30 * 60
    edith.touch()
    assert edith.attempt("0000") == AuthStatus("locked", "wrong_pin", 0)


def test_cancel_enters_conversation_only_mode():
    edith, *_ = session()

    assert edith.cancel() == AuthStatus("locked", "cancelled", 0)
    assert edith.conversation_only and not edith.unlocked


def test_unlock_from_conversation_only_mode():
    edith, *_ = session()
    edith.cancel()

    edith.attempt("0000")
    assert edith.conversation_only

    edith.attempt(PIN)
    assert edith.unlocked and not edith.conversation_only


def test_attempt_without_a_valid_lock_keeps_no_lock_file():
    edith, _, pins = session(valid_lock=False)

    assert edith.attempt(PIN) == AuthStatus("locked", "no_lock_file", 0)
    assert pins.checked == []


def test_attempt_when_unlocked_changes_nothing():
    edith, *_ = session(pin_required=False)

    assert edith.attempt("x") == AuthStatus("unlocked", "not_required", 0)


def unlocked_session(**options):
    edith, clock, pins = session(**options)
    edith.attempt(PIN)
    edith.touch()
    return edith, clock


def test_idle_relock_at_exactly_lock_after_min():
    edith, clock = unlocked_session()
    clock.now += 30 * 60

    assert edith.touch() == AuthStatus("locked", "idle", 0)
    assert not edith.unlocked and not edith.conversation_only


def test_no_relock_one_second_before():
    edith, clock = unlocked_session()
    clock.now += 30 * 60 - 1

    assert edith.touch() is None
    assert edith.unlocked


def test_activity_keeps_the_session_open():
    edith, clock = unlocked_session()

    for _ in range(6):
        clock.now += 10 * 60
        assert edith.touch() is None

    assert edith.unlocked


def test_first_message_never_relocks():
    edith, clock, _ = session()
    edith.attempt(PIN)
    clock.now += 99 * 60

    assert edith.touch() is None


def test_no_relock_when_the_pin_is_not_required():
    edith, clock, _ = session(pin_required=False)
    edith.touch()
    clock.now += 99 * 60

    assert edith.touch() is None
    assert edith.unlocked


def test_custom_lock_after_min():
    edith, clock = unlocked_session(lock_after_min=1)
    clock.now += 60

    assert edith.touch() == AuthStatus("locked", "idle", 0)


def test_touch_while_locked_does_not_report_a_change():
    edith, clock, _ = session()
    edith.touch()
    clock.now += 99 * 60

    assert edith.touch() is None
    assert edith.status == AuthStatus("locked", "start", 0)
