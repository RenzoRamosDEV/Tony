import pytest

from tests.fakes.desktop import FakeNotifier
from tony.apps.desktop.presenters.attention import NOTIFICATION_TITLE, ConfirmationAttention
from tony.core.events import core_events as ev

QUESTION = "Acción: borrar el archivo /home/renzo/notas/viejo.md. ¿Autoriza?"


def pending(task_id="t1", question=QUESTION):
    return ev.needs_confirmation(task_id, "filesystem.delete_file", "{}", question, True)


def make(hidden=True, notifier=None):
    notifier = notifier or FakeNotifier()
    reveals, reports = [], []
    attention = ConfirmationAttention(
        notifier,
        window_hidden=lambda: hidden,
        reveal=lambda edith: reveals.append(edith),
        report=reports.append,
    )
    return attention, notifier, reveals, reports


def test_hidden_window_gets_one_notification_with_the_question():
    attention, notifier, _, _ = make(hidden=True)
    attention.apply(pending())
    assert notifier.shown == [(NOTIFICATION_TITLE, QUESTION)]
    assert NOTIFICATION_TITLE == "Tony — Edith"


def test_visible_window_gets_none():
    attention, notifier, _, _ = make(hidden=False)
    attention.apply(pending())
    assert notifier.shown == []


def test_the_same_event_twice_notifies_once():
    attention, notifier, _, _ = make()
    event = pending()
    attention.apply(event)
    attention.apply(event)
    assert len(notifier.shown) == 1


def test_a_new_confirmation_notifies_again():
    attention, notifier, _, _ = make()
    attention.apply(pending("t1"))
    attention.apply(pending("t2"))
    assert len(notifier.shown) == 2


def test_click_reveals_the_edith_banner():
    attention, notifier, reveals, _ = make()
    attention.apply(pending())
    notifier.click()
    assert reveals == [True]


def test_failing_notifier_reports_once_and_stops_trying():
    notifier = FakeNotifier(error=OSError("no notification service"))
    attention, _, _, reports = make(notifier=notifier)
    attention.apply(pending("t1"))
    attention.apply(pending("t2"))
    [error] = reports
    assert (error["type"], error["source"], error["message"]) == (
        "error",
        "notifications",
        "no notification service",
    )


@pytest.mark.parametrize("event", [ev.token("jarvis", "x"), ev.error("front", "x")])
def test_other_events_are_ignored(event):
    attention, notifier, _, reports = make()
    attention.apply(event)
    assert notifier.shown == [] and reports == []
