from tests.fakes.fake_runtime import FakeRuntime
from tony.apps.desktop.app import launch, open_desktop


def fake_factory(runtimes):
    def factory(publish):
        runtimes.append(FakeRuntime(publish))
        return runtimes[-1]

    return factory


def test_open_desktop_shows_the_window_and_survives_an_error_event(qtbot, tmp_path):
    runtimes = []
    window, core = open_desktop(tmp_path, fake_factory(runtimes))
    qtbot.addWidget(window)

    assert window.isVisible() and core.is_alive()
    runtimes[0].publish({"type": "error", "ts": "x", "source": "front", "message": "model down"})
    qtbot.waitUntil(lambda: bool(window.presenters.chat.bubbles), timeout=2000)

    assert window.isVisible()
    assert "model down" in window.chat_view.html
    window.close()
    assert not core.is_alive()
    assert runtimes[0].stopped


def test_commands_from_the_window_reach_the_runtime(qtbot, tmp_path):
    runtimes = []
    window, core = open_desktop(tmp_path, fake_factory(runtimes))
    qtbot.addWidget(window)

    window.presenters.chat.send("Hola")
    qtbot.waitUntil(lambda: bool(runtimes[0].commands), timeout=2000)
    window.close()

    assert runtimes[0].commands == [{"type": "send_message", "text": "Hola"}]


def test_launch_runs_the_event_loop_and_stops_the_core(qtbot, tmp_path):
    runtimes, seen = [], []

    def run_loop(app, window):
        seen.append(window.isVisible())
        window.close()
        return 0

    assert launch(tmp_path, fake_factory(runtimes), run_loop=run_loop) == 0
    assert seen == [True]
    assert runtimes[0].stopped
