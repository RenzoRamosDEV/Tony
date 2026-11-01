from tests.core.guard.test_session import PIN, Clock, FakePins
from tests.fakes.pin import HANG, FakePinPrompt
from tony.core.guard.policy import Auth
from tony.core.guard.session import AuthStatus, EdithSession, SessionGate


def gate_for(answers, *, pin_required=True, valid_lock=True, state="idle", timeout=0.2):
    session = EdithSession(Auth(pin_required=pin_required), FakePins(valid_lock), monotonic=Clock())
    if state == "unlocked":
        session.attempt(PIN)
    elif state == "cancelled":
        session.cancel()
    prompt, changes = FakePinPrompt(answers), []
    gate = SessionGate(session, prompt, timeout_s=timeout, on_change=changes.append)
    return gate, prompt, session, changes


async def test_unlocked_passes_without_prompting():
    gate, prompt, *_ = gate_for([], state="unlocked")

    assert await gate.ensure_unlocked() is True
    assert prompt.shown == []


async def test_not_required_passes_without_prompting():
    gate, prompt, *_ = gate_for([], pin_required=False)

    assert await gate.ensure_unlocked() is True
    assert prompt.shown == []


async def test_conversation_only_refuses_without_prompting():
    gate, prompt, *_ = gate_for([PIN], state="cancelled")

    assert await gate.ensure_unlocked() is False
    assert prompt.shown == []


async def test_no_lock_file_refuses_without_prompting():
    gate, prompt, *_ = gate_for([PIN], valid_lock=False)

    assert await gate.ensure_unlocked() is False
    assert prompt.shown == []


async def test_locked_prompts_and_correct_pin_unlocks():
    gate, prompt, session, changes = gate_for([PIN])

    assert await gate.ensure_unlocked() is True
    assert prompt.shown == [AuthStatus("locked", "start", 0)]
    assert session.unlocked
    assert changes == [AuthStatus("unlocked", "unlocked", 0)]


async def test_wrong_pin_prompts_again_with_the_rejection():
    gate, prompt, *_ = gate_for(["0000", PIN])

    assert await gate.ensure_unlocked() is True
    assert prompt.shown == [AuthStatus("locked", "start", 0), AuthStatus("locked", "wrong_pin", 0)]


async def test_cancel_refuses_and_enters_conversation_only():
    gate, _, session, changes = gate_for([None])

    assert await gate.ensure_unlocked() is False
    assert session.conversation_only
    assert changes == [AuthStatus("locked", "cancelled", 0)]


async def test_no_answer_within_the_timeout_refuses():
    gate, _, session, _ = gate_for([HANG], timeout=0.05)

    assert await gate.ensure_unlocked() is False
    assert not session.unlocked and not session.conversation_only


async def test_timeout_covers_every_retry():
    gate, prompt, *_ = gate_for(["0000", "0000", HANG], timeout=0.05)

    assert await gate.ensure_unlocked() is False
    assert len(prompt.shown) == 3
