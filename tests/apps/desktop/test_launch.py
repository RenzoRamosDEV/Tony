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
