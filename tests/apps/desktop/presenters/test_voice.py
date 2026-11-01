import pytest

from tony.apps.desktop.presenters.voice import LISTENING_LABEL, MICROPHONE_LABEL, VoicePresenter
from tony.core.events import core_events as ev


def make():
    sent, changes = [], []
    presenter = VoicePresenter(sent.append)
    presenter.subscribe(lambda: changes.append(presenter.state))
    return presenter, sent, changes


def view(presenter):
    return (presenter.enabled, presenter.label)


def test_starts_loading_disabled_with_a_loading_tooltip():
    presenter, sent, _ = make()
    assert view(presenter) == (False, MICROPHONE_LABEL)
    assert "cargando" in presenter.tooltip.lower()
    presenter.toggle()
    assert sent == []


def test_unavailable_shows_the_reason_and_stays_disabled():
    presenter, sent, changes = make()
    presenter.apply(ev.voice_state("unavailable", "voice extra not installed"))
    assert view(presenter) == (False, MICROPHONE_LABEL)
    assert "voice extra not installed" in presenter.tooltip
    presenter.toggle()
    assert sent == [] and changes == ["unavailable"]


def test_ready_click_listens():
    presenter, sent, _ = make()
    presenter.apply(ev.voice_state("ready"))
    assert view(presenter) == (True, MICROPHONE_LABEL)
    presenter.toggle()
    assert sent == [{"type": "listen"}]


def test_listening_label_and_click_stops():
    presenter, sent, _ = make()
    presenter.apply(ev.voice_state("ready"))
    presenter.toggle()
    presenter.apply(ev.voice_state("listening"))
    assert view(presenter) == (True, LISTENING_LABEL)
    assert LISTENING_LABEL == "Escuchando…"
    presenter.toggle()
    assert sent == [{"type": "listen"}, {"type": "stop_listening"}]


@pytest.mark.parametrize("state", ["loading", "ready", "listening", "unavailable"])
def test_every_state_has_a_tooltip(state):
    presenter, _, _ = make()
    presenter.apply(ev.voice_state(state, "x" if state == "unavailable" else None))
    assert presenter.tooltip and presenter.state == state


def test_other_events_are_ignored():
    presenter, _, changes = make()
    presenter.apply(ev.token("jarvis", "x"))
    assert changes == [] and presenter.state == "loading"
