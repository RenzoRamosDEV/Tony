import pytest

from tony.apps.desktop.presenters.pin import PinPresenter
from tony.core.events import core_events as ev


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make():
    sent, changes, clock = [], [], Clock()
    presenter = PinPresenter(sent.append, monotonic=clock)
    presenter.subscribe(lambda: changes.append(True))
    return presenter, sent, changes, clock


def test_starts_hidden_and_unlocked():
    presenter, *_ = make()

    assert (presenter.mode, presenter.can_unlock) == ("hidden", False)


@pytest.mark.parametrize("reason", ["start", "idle"])
def test_asking_reasons_open_the_prompt(reason):
    presenter, _, changes, _ = make()

    presenter.apply(ev.auth("locked", reason, 0))

    assert (presenter.mode, presenter.input_enabled, presenter.remaining_s) == ("prompt", True, 0)
    assert presenter.can_unlock
    assert changes == [True]


@pytest.mark.parametrize("reason", ["wrong_pin", "backoff"])
def test_back_off_disables_input_and_counts_down(reason):
    presenter, _, changes, clock = make()

    presenter.apply(ev.auth("locked", reason, 10))
    assert (presenter.mode, presenter.input_enabled, presenter.remaining_s) == ("prompt", False, 10)

    clock.now += 4.2
    presenter.tick()
    assert (presenter.input_enabled, presenter.remaining_s) == (False, 6)

    clock.now += 5.8
    presenter.tick()
    assert (presenter.input_enabled, presenter.remaining_s) == (True, 0)
    assert len(changes) == 3


def test_wrong_pin_without_wait_keeps_input_enabled_and_says_so():
    presenter, *_ = make()

    presenter.apply(ev.auth("locked", "wrong_pin", 0))

    assert (presenter.mode, presenter.input_enabled) == ("prompt", True)
    assert "incorrecto" in presenter.message


def test_no_lock_file_explains_tony_pin_set():
    presenter, *_ = make()

    presenter.apply(ev.auth("locked", "no_lock_file", 0))

    assert presenter.mode == "explain"
    assert "tony pin set" in presenter.message


@pytest.mark.parametrize(
    ("state", "reason", "can_unlock"),
    [
        ("unlocked", "unlocked", False),
        ("unlocked", "not_required", False),
        ("locked", "cancelled", True),
    ],
)
def test_hidden_states(state, reason, can_unlock):
    presenter, *_ = make()
    presenter.apply(ev.auth("locked", "start", 0))

    presenter.apply(ev.auth(state, reason, 0))

    assert (presenter.mode, presenter.can_unlock) == ("hidden", can_unlock)


def test_submit_sends_the_pin():
    presenter, sent, *_ = make()
    presenter.apply(ev.auth("locked", "start", 0))

    presenter.submit("4821")

    assert sent == [{"type": "unlock", "pin": "4821"}]


def test_submit_is_ignored_while_input_is_disabled_or_empty():
    presenter, sent, *_ = make()
    presenter.apply(ev.auth("locked", "start", 0))
    presenter.submit("")
    presenter.apply(ev.auth("locked", "wrong_pin", 10))
    presenter.submit("4821")

    assert sent == []


def test_cancel_sends_a_null_pin_and_hides():
    presenter, sent, *_ = make()
    presenter.apply(ev.auth("locked", "start", 0))

    presenter.cancel()

    assert sent == [{"type": "unlock", "pin": None}]
    assert presenter.mode == "hidden"


def test_unlock_action_reopens_the_prompt_while_locked():
    presenter, sent, *_ = make()
    presenter.apply(ev.auth("locked", "cancelled", 0))

    presenter.request_unlock()

    assert presenter.mode == "prompt"
    assert sent == []


def test_unlock_action_does_nothing_when_unlocked():
    presenter, _, changes, _ = make()

    presenter.request_unlock()

    assert (presenter.mode, changes) == ("hidden", [])


def test_unrelated_events_change_nothing():
    presenter, _, changes, _ = make()

    presenter.apply(ev.token("jarvis", "x"))

    assert changes == []
