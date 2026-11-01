import threading

from tony.core.config.placeholders import SecretMasker
from tony.core.mcp.stderr import MaskedStderr

MASKER = SecretMasker({"s3cr3t"})


def written(tmp_path, *chunks):
    log = tmp_path / "logs" / "mcp" / "fs.log"
    with MaskedStderr(log, MASKER) as errlog:
        for chunk in chunks:
            errlog.write(chunk)
            errlog.flush()
    return log.read_text()


def test_secret_lines_are_masked(tmp_path):
    assert written(tmp_path, "auth with s3cr3t\n") == "auth with ***\n"


def test_plain_lines_unchanged_and_all_present_after_close(tmp_path):
    lines = [f"line {n} /home/renzo\n" for n in range(50)]

    assert written(tmp_path, *lines) == "".join(lines)


def test_partial_last_line_flushed_on_close(tmp_path):
    assert written(tmp_path, "start\n", "no newline s3cr3t") == "start\nno newline ***"


def test_appends_to_an_existing_log(tmp_path):
    written(tmp_path, "first\n")

    assert written(tmp_path, "second\n") == "first\nsecond\n"


def test_reader_thread_finished_after_close(tmp_path):
    before = set(threading.enumerate())
    stderr = MaskedStderr(tmp_path / "fs.log", MASKER)

    with stderr as errlog:
        errlog.write("x\n")
        reader = stderr.reader

    assert reader not in before
    assert not reader.is_alive()


def test_write_end_is_a_real_file_descriptor(tmp_path):
    with MaskedStderr(tmp_path / "fs.log", MASKER) as errlog:
        assert errlog.fileno() >= 0
