import pytest

from tony.apps.desktop.presenters.tray import NEUTRAL, TRAY_LOOKS, TrayPresenter
from tony.core.events import core_events as ev
from tony.core.events.messages import Ruling, TaskResult

RESULT = TaskResult(resumen="r")


def task_result(task_id="t1"):
    return ev.task_result(
        task_id, "viernes", "ok", RESULT, input_tokens=0, output_tokens=0, elapsed_ms=0
    )


def tool_call(task_id="t1"):
    return ev.tool_call(
        task_id,
        "viernes",
        "fs.delete",
        "{}",
        Ruling(verdict="confirm", rule="r", user_decision="allow"),
    )


def make():
    presenter = TrayPresenter()
    changes = []
    presenter.subscribe(lambda: changes.append(presenter.state))
    return presenter, changes


def test_starts_idle():
    assert TrayPresenter().state == "idle"


def test_turn_with_a_confirmation():
    presenter, _ = make()
    states = []
    for event in (
        ev.turn_started("jarvis", "text", "text", speaks=False, writes=True),
        ev.task_started("t1", "viernes", "Borra"),
        ev.needs_confirmation("t1", "fs.delete", "{}", "¿Autoriza?", True),
        tool_call(),
        task_result(),
        ev.turn_result("jarvis", "Hecho", "text"),
    ):
        presenter.apply(event)
        states.append(presenter.state)
    assert states == ["working", "working", "awaiting_confirmation", "working", "working", "idle"]


def test_front_error_returns_to_idle_but_other_errors_do_not():
    presenter, _ = make()
    presenter.apply(ev.turn_started("jarvis", "text", "text", speaks=False, writes=True))
    presenter.apply(ev.error("voice.tts", "x"))
    assert presenter.state == "working"
    presenter.apply(ev.error("front", "model down"))
    assert presenter.state == "idle"


def test_unrelated_tool_call_keeps_awaiting():
    presenter, _ = make()
    presenter.apply(ev.needs_confirmation("t1", "fs.delete", "{}", "¿Autoriza?", True))
    presenter.apply(tool_call("t2"))
    assert presenter.state == "awaiting_confirmation"
    presenter.apply(task_result("t1"))
    assert presenter.state == "working"


def test_changes_are_notified_only_when_the_state_changes():
    presenter, changes = make()
    presenter.apply(ev.turn_started("jarvis", "text", "text", speaks=False, writes=True))
    presenter.apply(ev.task_started("t1", "viernes", "o"))
    presenter.apply(ev.token("jarvis", "x"))
    assert changes == ["working"]


@pytest.mark.parametrize(
    ("state", "tooltip", "colour"),
    [
        ("idle", "Tony — en espera", "#6B7280"),
        ("working", "Tony — trabajando", "#2F6FED"),
        ("awaiting_confirmation", "Tony — esperando confirmación", "#E0A100"),
    ],
)
def test_tooltip_and_colour_per_state(state, tooltip, colour):
    presenter = TrayPresenter()
    presenter.state = state
    assert (presenter.tooltip, presenter.colour) == (tooltip, colour)
    assert TRAY_LOOKS[state] == (tooltip, colour)


def test_idle_uses_the_neutral_colour():
    assert NEUTRAL == "#6B7280"
    assert TRAY_LOOKS["idle"][1] == NEUTRAL
