import json

import pytest
from PySide6.QtWidgets import QLabel

from tests.fakes.fake_runtime import FakeRuntime
from tests.fakes.web_view import FakeWebView
from tony.apps.desktop.app import launch, open_desktop
from tony.apps.desktop.page_policy import BUILD_COMMAND
from tony.core.events import core_events as ev


def fake_factory(runtimes):
    def factory(publish):
        runtimes.append(FakeRuntime(publish))
        return runtimes[-1]

    return factory


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / "index.html").write_text("<!doctype html>")
    return folder


def open_window(qtbot, tmp_path, dist, runtimes):
    window, core = open_desktop(
        tmp_path, fake_factory(runtimes), view_factory=FakeWebView, dist=dist
    )
    qtbot.addWidget(window)
    return window, core


def page_events(window):
    received = []
    window.bridge.event.connect(lambda text: received.append(json.loads(text)))
    return received


def test_the_built_page_is_loaded_from_a_file_url_with_the_tony_channel(qtbot, tmp_path, dist):
    window, core = open_window(qtbot, tmp_path, dist, [])

    view = window.centralWidget()
    assert isinstance(view, FakeWebView)
    assert view.home.isLocalFile()
    assert view.home.toLocalFile() == str(dist / "index.html")
    assert view.channel_objects.keys() == {"tony", "windowControls"}
    assert view.channel_objects["tony"] is window.bridge
    assert window.isVisible() and core.is_alive()
    window.close()


def test_without_a_build_the_window_shows_the_build_command_and_the_core_runs(qtbot, tmp_path):
    runtimes, dispatched = [], []
    window, core = open_window(qtbot, tmp_path, tmp_path / "missing", runtimes)
    window.dispatched.connect(dispatched.append)

    label = window.centralWidget()
    assert isinstance(label, QLabel)
    assert BUILD_COMMAND in label.text()
    assert core.is_alive()
    runtimes[0].publish(ev.voice_state("ready"))
    qtbot.waitUntil(lambda: bool(dispatched), timeout=5000)
    assert dispatched[0]["type"] == "voice_state"
    window.close()


def test_core_events_reach_the_page_as_json_once_ready(qtbot, tmp_path, dist):
    runtimes = []
    window, _ = open_window(qtbot, tmp_path, dist, runtimes)
    received = page_events(window)
    runtimes[0].publish(ev.token("jarvis", "perdido"))
    qtbot.wait(50)

    window.bridge.ready()
    event = ev.token("jarvis", "Hola")
    runtimes[0].publish(event)

    qtbot.waitUntil(lambda: bool(received), timeout=5000)
    assert received == [event]
    window.close()


def test_page_commands_reach_the_runtime(qtbot, tmp_path, dist):
    runtimes = []
    window, _ = open_window(qtbot, tmp_path, dist, runtimes)

    window.bridge.send('{"type": "send_message", "text": "Hola"}')
    qtbot.waitUntil(lambda: bool(runtimes[0].commands), timeout=5000)
    window.close()

    assert runtimes[0].commands == [{"type": "send_message", "text": "Hola"}]


def test_refused_page_commands_reach_the_tray_path_but_not_the_core(qtbot, tmp_path, dist):
    runtimes, dispatched = [], []
    window, _ = open_window(qtbot, tmp_path, dist, runtimes)
    window.dispatched.connect(dispatched.append)
    received = page_events(window)
    window.bridge.ready()

    window.bridge.send('{"type": "stop"}')
    qtbot.wait(50)

    assert [(e["type"], e["source"]) for e in dispatched] == [("error", "stop")]
    assert received == dispatched
    assert runtimes[0].commands == [] and not runtimes[0].stopped
    window.close()


def test_reveal_on_the_confirmation_restores_and_asks_the_page_to_focus(qtbot, tmp_path, dist):
    window, _ = open_window(qtbot, tmp_path, dist, [])
    focus = []
    window.bridge.focusConfirmation.connect(lambda: focus.append(True))
    window.showMinimized()

    window.reveal(confirmation=True)

    assert not window.isMinimized() and window.isVisible()
    assert focus == [True]
    window.reveal()
    assert focus == [True]
    window.close()


def test_closing_the_window_stops_the_core(qtbot, tmp_path, dist):
    runtimes = []
    window, core = open_window(qtbot, tmp_path, dist, runtimes)

    window.close()

    assert not core.is_alive()
    assert runtimes[0].stopped


def test_launch_runs_the_event_loop_and_stops_the_core(qtbot, tmp_path):
    from tests.apps.desktop.test_launch import FakeChannel

    runtimes, seen = [], []

    def run_loop(app, window):
        seen.append(window.isVisible())
        window.close()
        return 0

    channel = FakeChannel(answers=False)
    assert launch(tmp_path, fake_factory(runtimes), run_loop=run_loop, channel=channel) == 0
    assert seen == [True]
    assert runtimes[0].stopped


def test_the_default_runtime_preloads_voice_with_the_real_engine_loader(tmp_path):
    from tony.apps.desktop.app import default_runtime_factory
    from tony.core.voice.engines.loader import load_engines

    runtime = default_runtime_factory(tmp_path)(lambda event: None)

    assert runtime.voice is not None
    assert runtime.voice.loader is load_engines
