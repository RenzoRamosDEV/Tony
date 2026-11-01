from tests.apps.desktop.test_app import fake_factory
from tony.apps.desktop.app import launch


class FakeChannel:
    def __init__(self, answers: bool) -> None:
        self.answers = answers
        self.sent: list[str] = []
        self.served = []

    def send(self, message: str) -> bool:
        self.sent.append(message)
        return self.answers

    def serve(self, on_message) -> None:
        self.served.append(on_message)

    def close(self) -> None:
        return None


def closing_loop(seen):
    def run_loop(app, window):
        seen.append(window)
        window.close()
        return 0

    return run_loop


def test_a_running_instance_answers_and_no_window_opens(qtbot, tmp_path):
    channel, seen, runtimes = FakeChannel(answers=True), [], []

    code = launch(tmp_path, fake_factory(runtimes), run_loop=closing_loop(seen), channel=channel)

    assert code == 0
    assert (channel.sent, seen, runtimes) == (["show"], [], [])


def test_focus_asks_the_running_instance_to_focus(qtbot, tmp_path):
    channel = FakeChannel(answers=True)

    assert launch(tmp_path, fake_factory([]), focus=True, channel=channel) == 0
    assert channel.sent == ["focus"]


def test_without_an_instance_the_window_opens_and_the_channel_is_served(qtbot, tmp_path):
    channel, seen, runtimes = FakeChannel(answers=False), [], []

    code = launch(tmp_path, fake_factory(runtimes), run_loop=closing_loop(seen), channel=channel)

    assert code == 0
    assert len(seen) == 1 and len(channel.served) == 1
    assert runtimes[0].commands == []


def test_focus_without_an_instance_submits_listen(qtbot, tmp_path):
    channel, runtimes = FakeChannel(answers=False), []

    def run_loop(app, window):
        qtbot.waitUntil(lambda: bool(runtimes[0].commands), timeout=5000)
        window.close()
        return 0

    launch(tmp_path, fake_factory(runtimes), focus=True, run_loop=run_loop, channel=channel)

    assert runtimes[0].commands == [{"type": "listen"}]


def test_channel_messages_reveal_and_focus_listens(qtbot, tmp_path):
    channel, runtimes = FakeChannel(answers=False), []
    revealed = []

    def run_loop(app, window):
        window.reveal = lambda edith=False: revealed.append(edith)
        channel.served[0]("show")
        channel.served[0]("focus")
        qtbot.waitUntil(lambda: bool(runtimes[0].commands), timeout=5000)
        window.close()
        return 0

    launch(tmp_path, fake_factory(runtimes), run_loop=run_loop, channel=channel)

    assert revealed == [False, False]
    assert runtimes[0].commands == [{"type": "listen"}]


def test_the_x11_hotkey_reveals_and_listens(qtbot, tmp_path):
    import threading

    from tests.fakes.desktop import FakeHotkeys

    channel, runtimes, revealed = FakeChannel(answers=False), [], []
    FakeHotkeys.instances.clear()

    def run_loop(app, window):
        window.reveal = lambda edith=False: revealed.append(edith)
        [hotkeys] = FakeHotkeys.instances
        assert list(hotkeys.mapping) == ["<cmd>+j"]
        presser = threading.Thread(target=hotkeys.press, args=("<cmd>+j",))
        presser.start()
        presser.join(5)
        qtbot.waitUntil(lambda: bool(runtimes[0].commands), timeout=5000)
        window.close()
        return 0

    launch(
        tmp_path,
        fake_factory(runtimes),
        run_loop=run_loop,
        channel=channel,
        environ={"XDG_SESSION_TYPE": "x11"},
        hotkeys=FakeHotkeys,
    )

    assert revealed == [False]
    assert runtimes[0].commands == [{"type": "listen"}]
    assert FakeHotkeys.instances[0].stopped


def test_an_invalid_hotkey_is_shown_and_the_app_keeps_running(qtbot, tmp_path):
    from tests.fakes.desktop import FakeHotkeys

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tony.yaml").write_text("desktop:\n  hotkey: 'Super+'\n")
    seen = []

    def run_loop(app, window):
        seen.append([b.markdown for b in window.presenters.chat.bubbles])
        window.close()
        return 0

    code = launch(
        tmp_path,
        fake_factory([]),
        run_loop=run_loop,
        channel=FakeChannel(answers=False),
        environ={"XDG_SESSION_TYPE": "x11"},
        hotkeys=FakeHotkeys,
    )

    assert code == 0
    [bubbles] = seen
    assert any("desktop.hotkey" in text for text in bubbles)


def test_no_hotkey_on_wayland(qtbot, tmp_path):
    from tests.fakes.desktop import FakeHotkeys

    FakeHotkeys.instances.clear()
    launch(
        tmp_path,
        fake_factory([]),
        run_loop=closing_loop([]),
        channel=FakeChannel(answers=False),
        environ={"XDG_SESSION_TYPE": "wayland"},
        hotkeys=FakeHotkeys,
    )
    assert FakeHotkeys.instances == []


def test_a_hidden_window_notifies_pending_confirmations(qtbot, tmp_path):
    from tests.fakes.desktop import FakeNotifier
    from tony.core.events import core_events as ev

    notifier, revealed, seen = FakeNotifier(), [], []

    def run_loop(app, window):
        window.hide()
        window.dispatch(ev.needs_confirmation("t1", "fs.delete", "{}", "¿Autoriza?", True))
        seen.append(list(notifier.shown))
        window.reveal = lambda edith=False: revealed.append(edith)
        notifier.click()
        window.close()
        return 0

    launch(
        tmp_path,
        fake_factory([]),
        run_loop=run_loop,
        channel=FakeChannel(answers=False),
        notifier=lambda: notifier,
    )

    assert seen == [[("Tony — Edith", "¿Autoriza?")]]
    assert revealed == [True]


def test_a_visible_window_does_not_notify(qtbot, tmp_path):
    from tests.fakes.desktop import FakeNotifier
    from tony.core.events import core_events as ev

    notifier = FakeNotifier()

    def run_loop(app, window):
        window.dispatch(ev.needs_confirmation("t1", "fs.delete", "{}", "¿Autoriza?", True))
        window.close()
        return 0

    launch(
        tmp_path,
        fake_factory([]),
        run_loop=run_loop,
        channel=FakeChannel(answers=False),
        notifier=lambda: notifier,
    )

    assert notifier.shown == []
