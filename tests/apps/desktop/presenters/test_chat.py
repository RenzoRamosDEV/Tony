import pytest

from tony.apps.desktop.presenters.chat import NEUTRAL, ChatPresenter
from tony.core.events import core_events as ev
from tony.core.events.messages import TaskResult


def make():
    sent, changes = [], []
    presenter = ChatPresenter(sent.append)
    presenter.subscribe(lambda: changes.append(len(presenter.bubbles)))
    return presenter, sent, changes


def summary(presenter):
    return [(b.agent, b.label, b.colour, b.markdown, b.open) for b in presenter.bubbles]


def test_send_adds_a_user_bubble_and_submits_the_message():
    presenter, sent, changes = make()

    presenter.send("Hola")

    assert summary(presenter) == [("user", "Tú", NEUTRAL, "Hola", False)]
    assert sent == [{"type": "send_message", "text": "Hola"}]
    assert changes == [1]


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_messages_are_not_sent(blank):
    presenter, sent, changes = make()

    presenter.send(blank)

    assert (presenter.bubbles, sent, changes) == ([], [], [])


def test_tokens_of_one_agent_grow_one_bubble():
    presenter, _, changes = make()

    presenter.apply(ev.token("jarvis", "Buenas"))
    presenter.apply(ev.token("jarvis", " **tardes**"))

    assert summary(presenter) == [("jarvis", "Jarvis", "#2F6FED", "Buenas **tardes**", True)]
    assert presenter.bubbles[0].html == "<p>Buenas <strong>tardes</strong></p>\n"
    assert changes == [1, 1]


@pytest.mark.parametrize(
    ("agent", "colour"),
    [("viernes", "#2E9E5B"), ("edith", "#E0A100"), ("otro", NEUTRAL), ("Jarvis", NEUTRAL)],
)
def test_agent_colours(agent, colour):
    presenter, *_ = make()

    presenter.apply(ev.token(agent, "x"))

    assert presenter.bubbles[0].colour == colour


def test_another_agent_opens_a_new_bubble():
    presenter, *_ = make()

    presenter.apply(ev.token("jarvis", "a"))
    presenter.apply(ev.token("viernes", "b"))

    assert [b.agent for b in presenter.bubbles] == ["jarvis", "viernes"]


def test_turn_result_closes_the_bubble_so_the_next_token_opens_another():
    presenter, *_ = make()

    presenter.apply(ev.token("jarvis", "uno"))
    presenter.apply(ev.turn_result("jarvis", "uno", "auto"))
    presenter.apply(ev.token("jarvis", "dos"))

    assert summary(presenter) == [
        ("jarvis", "Jarvis", "#2F6FED", "uno", False),
        ("jarvis", "Jarvis", "#2F6FED", "dos", True),
    ]


def test_turn_result_without_tokens_adds_a_closed_bubble():
    presenter, *_ = make()

    presenter.apply(ev.turn_result("jarvis", "Hecho.", "auto"))

    assert summary(presenter) == [("jarvis", "Jarvis", "#2F6FED", "Hecho.", False)]


def test_empty_turn_result_without_tokens_adds_nothing():
    presenter, *_ = make()

    presenter.apply(ev.turn_result("jarvis", "", "auto"))

    assert presenter.bubbles == []


def test_task_result_does_not_close_the_bubble():
    presenter, *_ = make()
    done = TaskResult(resumen="")

    presenter.apply(ev.token("jarvis", "uno"))
    presenter.apply(
        ev.task_result("t", "viernes", "ok", done, input_tokens=0, output_tokens=0, elapsed_ms=0)
    )

    assert presenter.bubbles[0].open


def test_error_adds_a_system_bubble():
    presenter, *_ = make()

    presenter.apply(ev.token("jarvis", "uno"))
    presenter.apply(ev.error("front", "model down"))

    assert summary(presenter) == [
        ("jarvis", "Jarvis", "#2F6FED", "uno", False),
        ("system", "Tony", NEUTRAL, "Error (front): model down", False),
    ]


def test_progress_adds_a_closed_front_agent_bubble():
    presenter, *_ = make()

    presenter.apply(ev.progress("jarvis", "Un momento, señor; estoy en ello."))

    assert summary(presenter) == [
        ("jarvis", "Jarvis", "#2F6FED", "Un momento, señor; estoy en ello.", False)
    ]


def test_mode_follows_reply_mode_events():
    presenter, _, changes = make()

    assert presenter.mode == "auto"
    presenter.apply(ev.reply_mode("voice"))

    assert presenter.mode == "voice"
    assert changes == [0]


def test_selecting_a_mode_sends_set_mode():
    presenter, sent, _ = make()

    presenter.select_mode("text")

    assert sent == [{"type": "set_mode", "mode": "text"}]


def test_selecting_the_current_mode_sends_nothing():
    presenter, sent, _ = make()

    presenter.select_mode("auto")

    assert sent == []


def test_unrelated_events_change_nothing():
    presenter, _, changes = make()

    presenter.apply(ev.auth("locked", "start", 0))
    presenter.apply(ev.mcp_status("viernes", "fs", up=True, reason=None))

    assert (presenter.bubbles, changes) == ([], [])
