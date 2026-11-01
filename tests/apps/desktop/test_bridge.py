import threading
import time

from tests.fakes.fake_runtime import FakeRuntime
from tony.apps.desktop.bridge import CoreThread, QtEventBridge


def start(qtbot, events=None, **options):
    bridge = QtEventBridge()
    if events is not None:
        bridge.event.connect(events.append)
    runtimes = []

    def factory(publish):
        runtimes.append(FakeRuntime(publish, **options))
        return runtimes[0]

    core = CoreThread(factory, bridge)
    core.start()
    return core, bridge, runtimes[0]


def test_submit_reaches_the_runtime_on_the_core_thread(qtbot):
    core, bridge, runtime = start(qtbot)
    main = threading.get_ident()

    with qtbot.waitSignal(bridge.event, timeout=2000) as signal:
        core.submit({"type": "send_message", "text": "Hola"})
    core.stop()

    assert runtime.commands == [{"type": "send_message", "text": "Hola"}]
    assert set(runtime.submit_threads) == {runtime.serve_thread}
    assert runtime.serve_thread != main
    assert signal.args[0]["thread"] == runtime.serve_thread


def test_events_arrive_on_the_main_thread(qtbot):
    core, bridge, _ = start(qtbot)
    received_on = []
    bridge.event.connect(lambda event: received_on.append(threading.get_ident()))

    with qtbot.waitSignal(bridge.event, timeout=2000):
        core.submit({"type": "x"})
    core.stop()

    assert received_on == [threading.get_ident()]


def test_an_exception_in_the_runtime_is_an_error_event_and_the_core_keeps_going(qtbot):
    core, bridge, runtime = start(qtbot)
    events = []
    bridge.event.connect(events.append)

    with qtbot.waitSignal(bridge.event, timeout=2000):
        core.submit({"type": "boom"})
    with qtbot.waitSignal(bridge.event, timeout=2000):
        core.submit({"type": "after"})
    core.stop()

    assert events[0]["type"] == "error" and "boom" in events[0]["message"]
    assert events[1]["command"] == {"type": "after"}


def test_a_crashing_serve_is_reported_and_stop_still_works(qtbot):
    events = []
    core, _, _ = start(qtbot, events, crash_on_serve=True)

    qtbot.waitUntil(lambda: bool(events), timeout=2000)
    started = time.monotonic()
    core.stop()

    assert events[0]["type"] == "error" and "serve crashed" in events[0]["message"]
    assert time.monotonic() - started < 5
    assert not core.is_alive()


def test_stop_joins_the_thread_within_five_seconds(qtbot):
    core, _, runtime = start(qtbot)

    started = time.monotonic()
    core.stop()

    assert runtime.stopped
    assert not core.is_alive()
    assert time.monotonic() - started < 5


def test_stop_twice_is_harmless(qtbot):
    core, *_ = start(qtbot)

    core.stop()
    core.stop()

    assert not core.is_alive()
