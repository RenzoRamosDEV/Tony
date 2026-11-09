import subprocess
from pathlib import Path

import pytest

from tony.core.music.ports import MusicError, Track
from tony.core.music.ytdlp import YtDlpResolver


class FakeRun:
    def __init__(self, stdout="", returncode=0, stderr="", raises=None):
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.raises = raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return self.result


def resolver(run, binary="/usr/bin/yt-dlp"):
    return YtDlpResolver(run=run, find_binary=lambda: binary)


def test_resolves_title_and_stream_url_from_two_output_lines():
    run = FakeRun(stdout="Bohemian Rhapsody\nhttps://stream/queen\n")

    assert resolver(run).resolve("queen") == Track("Bohemian Rhapsody", "https://stream/queen")


def test_query_is_one_argv_element_without_a_shell():
    run = FakeRun(stdout="t\nu\n")
    hostile = "x; rm -rf ~ $(whoami) `id` | cat"

    resolver(run).resolve(hostile)

    argv, kwargs = run.calls[0]
    assert argv[0] == "/usr/bin/yt-dlp"
    assert argv.count(f"ytsearch1:{hostile}") == 1
    assert not kwargs.get("shell")
    assert kwargs["timeout"] > 0


def test_empty_output_means_nothing_found():
    with pytest.raises(MusicError, match="no encontré nada para «zzz»"):
        resolver(FakeRun(stdout="")).resolve("zzz")


def test_single_line_output_means_nothing_found():
    with pytest.raises(MusicError, match="no encontré nada"):
        resolver(FakeRun(stdout="only a title\n")).resolve("zzz")


def test_missing_binary_asks_to_install_it():
    run = FakeRun()

    with pytest.raises(MusicError, match="instala yt-dlp"):
        resolver(run, binary=None).resolve("x")
    assert run.calls == []


def test_vanished_binary_asks_to_install_it():
    with pytest.raises(MusicError, match="instala yt-dlp"):
        resolver(FakeRun(raises=FileNotFoundError())).resolve("x")


def test_failure_reports_last_stderr_line():
    run = FakeRun(returncode=1, stderr="warn\nERROR: network down\n")

    with pytest.raises(MusicError, match="yt-dlp falló: ERROR: network down"):
        resolver(run).resolve("x")


def test_timeout_is_reported():
    run = FakeRun(raises=subprocess.TimeoutExpired("yt-dlp", 30))

    with pytest.raises(MusicError, match="tardó demasiado"):
        resolver(run).resolve("x")


def test_binary_is_found_on_path_first(tmp_path):
    from tony.core.music.ytdlp import find_ytdlp

    local = tmp_path / ".local" / "bin" / "yt-dlp"
    local.parent.mkdir(parents=True)
    local.write_text("")
    local.chmod(0o755)

    assert find_ytdlp(which=lambda name: "/usr/bin/yt-dlp", home=tmp_path) == "/usr/bin/yt-dlp"
    assert find_ytdlp(which=lambda name: None, home=tmp_path) == str(local)


def test_binary_not_found_anywhere_is_none(tmp_path):
    from tony.core.music.ytdlp import find_ytdlp

    assert find_ytdlp(which=lambda name: None, home=Path(tmp_path)) is None
