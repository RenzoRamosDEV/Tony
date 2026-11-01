import threading

from tony.core.voice.stages import STOP_TIMEOUT_S, StageThread


class Reports:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []
        self.event = threading.Event()

    def __call__(self, source: str, message: str) -> None:
        self.items.append((source, message))
        self.event.set()


def test_items_are_handled_in_order_on_a_named_thread():
    handled, names, done = [], [], threading.Event()

    def handle(item):
        handled.append(item)
        names.append(threading.current_thread().name)
        if item == 3:
            done.set()

    stage = StageThread("tts", handle, Reports())
    stage.start()
    for item in (1, 2, 3):
        stage.put(item)
    assert done.wait(5)
    stage.stop()
    assert handled == [1, 2, 3]
    assert set(names) == {"tony-tts"}


def test_a_failing_item_is_reported_and_the_next_one_handled():
    handled, done, reports = [], threading.Event(), Reports()

    def handle(item):
        if item == "mal":
            raise RuntimeError("se rompió")
        handled.append(item)
        done.set()

    stage = StageThread("playback", handle, reports)
    stage.start()
    stage.put("mal")
    stage.put("bien")
    assert done.wait(5)
    stage.stop()
    assert reports.items == [("voice.playback", "se rompió")]
    assert handled == ["bien"]


def test_an_error_without_message_reports_its_type():
    reports = Reports()

    def handle(item):
        raise ValueError()

    stage = StageThread("stt", handle, reports)
    stage.start()
    stage.put(1)
    assert reports.event.wait(5)
    stage.stop()
    assert reports.items == [("voice.stt", "ValueError")]


def test_stop_joins_the_thread_within_the_timeout():
    stage = StageThread("vad", lambda item: None, Reports())
    stage.start()
    stage.stop()
    assert STOP_TIMEOUT_S == 2
    assert not stage.is_alive()


def test_stop_without_start_is_harmless():
    stage = StageThread("vad", lambda item: None, Reports())
    stage.stop()
    assert not stage.is_alive()


def test_clear_drops_queued_items():
    gate, handled, done = threading.Event(), [], threading.Event()

    def handle(item):
        gate.wait(5)
        handled.append(item)
        if item == "last":
            done.set()

    stage = StageThread("tts", handle, Reports())
    stage.start()
    stage.put("first")
    stage.put("queued")
    stage.clear()
    stage.put("last")
    gate.set()
    assert done.wait(5)
    stage.stop()
    assert "queued" not in handled and handled[-1] == "last"
