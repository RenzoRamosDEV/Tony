import tempfile
from pathlib import Path

import pytest

from tests.fakes.fake_mpv import FakeMpv
from tony.core.music.mpv import MpvBackend
from tony.core.music.ports import MusicError, Status, Track

A = Track("Song A", "https://stream/a")
B = Track("Cancion, con «comas» y ñ", "https://stream/b")


@pytest.fixture
def socket_path():
    with tempfile.TemporaryDirectory(prefix="tm") as folder:
        yield Path(folder) / "m.sock"


@pytest.fixture
def mpv(socket_path):
    fake = FakeMpv(socket_path)
    yield fake
    fake.close()


class Spawner:
    """Stands in for launching mpv: starts the fake server, or does nothing."""

    def __init__(self, mpv: FakeMpv | None):
        self.mpv = mpv
        self.argvs: list[list[str]] = []

    def __call__(self, argv):
        self.argvs.append(argv)
        if self.mpv:
            self.mpv.start()


def backend(socket_path, spawner, binary="/usr/bin/mpv"):
    return MpvBackend(
        socket_path,
        spawn=spawner,
        find_binary=lambda: binary,
        wait_seconds=0.3,
        poll_seconds=0.01,
    )


@pytest.fixture
def running(mpv, socket_path):
    mpv.start()
    spawner = Spawner(None)
    return backend(socket_path, spawner), mpv, spawner


def test_load_spawns_headless_mpv_when_socket_is_dead_then_plays(mpv, socket_path):
    spawner = Spawner(mpv)

    backend(socket_path, spawner).load(A)

    argv = spawner.argvs[0]
    assert argv[0] == "/usr/bin/mpv"
    assert {"--no-video", "--idle=yes", f"--input-ipc-server={socket_path}"} <= set(argv)
    assert [item["url"] for item in mpv.playlist] == [A.url]
    assert mpv.current["title"] == "Song A"


def test_mpv_announces_itself_to_the_sound_system_as_tony(mpv, socket_path):
    spawner = Spawner(mpv)

    backend(socket_path, spawner).load(A)

    assert "--audio-client-name=Tony" in spawner.argvs[0]


def test_stale_socket_file_is_replaced_before_spawning(mpv, socket_path):
    socket_path.write_text("")
    spawner = Spawner(mpv)

    backend(socket_path, spawner).load(A)

    assert len(spawner.argvs) == 1 and mpv.current["title"] == "Song A"


def test_live_socket_is_reused_without_spawning(running):
    sut, mpv, spawner = running

    sut.load(A)

    assert spawner.argvs == []


def test_missing_mpv_asks_to_install_it(socket_path):
    spawner = Spawner(None)

    with pytest.raises(MusicError, match="instala mpv"):
        backend(socket_path, spawner, binary=None).load(A)
    assert spawner.argvs == []


def test_mpv_that_never_opens_its_socket_is_an_error(socket_path):
    with pytest.raises(MusicError, match="mpv no respondió"):
        backend(socket_path, Spawner(None)).load(A)


def test_load_replaces_queue_and_unpauses(running):
    sut, mpv, _ = running
    sut.load(A)
    sut.append(B)
    sut.pause()

    sut.load(B)

    assert [item["title"] for item in mpv.playlist] == [B.title]
    assert mpv.pause is False


def test_append_to_idle_player_starts_it_and_titles_survive_special_characters(running):
    sut, mpv, _ = running

    sut.append(B)

    assert mpv.current["title"] == B.title


def test_append_keeps_current_track_and_grows_queue(running):
    sut, mpv, _ = running
    sut.load(A)

    sut.append(B)

    assert [item["title"] for item in mpv.playlist] == [A.title, B.title] and mpv.pos == 0


def test_pause_and_resume_toggle_the_property(running):
    sut, mpv, _ = running
    sut.load(A)

    sut.pause()
    assert mpv.pause is True
    sut.resume()
    assert mpv.pause is False


def test_volume_is_set(running):
    sut, mpv, _ = running
    sut.load(A)

    sut.set_volume(35)

    assert mpv.volume == 35


def test_next_and_previous_move_through_the_queue(running):
    sut, mpv, _ = running
    sut.load(A)
    sut.append(B)

    sut.next()
    assert mpv.pos == 1
    sut.previous()
    assert mpv.pos == 0


def test_next_on_last_and_previous_on_first_explain_why(running):
    sut, mpv, _ = running
    sut.load(A)

    with pytest.raises(MusicError, match="No hay más canciones en la cola"):
        sut.next()
    with pytest.raises(MusicError, match="No hay canción anterior"):
        sut.previous()
    assert mpv.pos == 0


def test_status_reports_current_track(running):
    sut, mpv, _ = running
    sut.load(A)
    sut.pause()
    sut.set_volume(40)

    assert sut.status() == Status("Song A", paused=True, volume=40, position=12.5, duration=200.0)


def test_status_tolerates_unknown_times(running):
    sut, mpv, _ = running
    sut.load(A)
    mpv.position = mpv.duration = None

    status = sut.status()

    assert (status.position, status.duration) == (None, None)


def test_status_is_none_when_idle(running):
    sut, _, _ = running

    assert sut.status() is None


def test_status_is_none_when_mpv_is_not_running_and_does_not_spawn(socket_path):
    spawner = Spawner(None)

    assert backend(socket_path, spawner).status() is None
    assert spawner.argvs == []


def test_status_is_none_even_if_mpv_is_not_installed(socket_path):
    assert backend(socket_path, Spawner(None), binary=None).status() is None


@pytest.mark.parametrize("action", ["pause", "resume", "next", "previous", "stop"])
def test_controls_without_mpv_say_nothing_is_playing_and_never_spawn(socket_path, action):
    spawner = Spawner(None)

    with pytest.raises(MusicError, match="No hay nada reproduciéndose"):
        getattr(backend(socket_path, spawner), action)()
    assert spawner.argvs == []


def test_volume_without_mpv_says_nothing_is_playing(socket_path):
    with pytest.raises(MusicError, match="No hay nada reproduciéndose"):
        backend(socket_path, Spawner(None)).set_volume(10)


@pytest.mark.parametrize("action", ["pause", "resume", "next", "previous", "stop"])
def test_controls_with_idle_mpv_say_nothing_is_playing(running, action):
    sut, _, _ = running

    with pytest.raises(MusicError, match="No hay nada reproduciéndose"):
        getattr(sut, action)()


def test_stop_clears_everything(running):
    sut, mpv, _ = running
    sut.load(A)
    sut.append(B)

    sut.stop()

    assert mpv.idle and mpv.playlist == []


def test_mpv_command_error_surfaces_its_message(running):
    sut, mpv, _ = running
    sut.load(A)
    mpv._set = lambda name, value: {"error": "boom"}

    with pytest.raises(MusicError, match="mpv: boom"):
        sut.pause()
