import pytest

from tony.core.config.placeholders import SecretMasker
from tony.core.memory.preferences import PREFERENCES_FILE, PreferencesFile


def prefs(tmp_path, content=None):
    if content is not None:
        path = tmp_path / PREFERENCES_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return PreferencesFile(tmp_path, SecretMasker({"s3cr3t"}))


def text(tmp_path):
    return (tmp_path / PREFERENCES_FILE).read_text()


def test_missing_file_reads_as_empty(tmp_path):
    assert prefs(tmp_path).read() == ""


def test_read_returns_content(tmp_path):
    assert prefs(tmp_path, "- uno\n").read() == "- uno\n"


def test_append_creates_folder_and_file(tmp_path):
    prefs(tmp_path).append_line("Prefiero respuestas cortas")

    assert text(tmp_path) == "- Prefiero respuestas cortas\n"


def test_append_adds_after_existing_lines(tmp_path):
    prefs(tmp_path, "- uno\n").append_line("dos")

    assert text(tmp_path) == "- uno\n- dos\n"


def test_append_adds_a_newline_when_the_file_lacks_one(tmp_path):
    prefs(tmp_path, "- uno").append_line("dos")

    assert text(tmp_path) == "- uno\n- dos\n"


@pytest.mark.parametrize(
    ("raw", "line"),
    [(" uno\ndos ", "- uno dos"), ("a\r\nb\rc", "- a b c"), ("\tx\t", "- x")],
)
def test_append_normalises_line_breaks_and_surrounding_spaces(tmp_path, raw, line):
    prefs(tmp_path).append_line(raw)

    assert text(tmp_path) == f"{line}\n"


def test_append_masks_secret_values(tmp_path):
    prefs(tmp_path).append_line("mi clave es s3cr3t")

    assert text(tmp_path) == "- mi clave es ***\n"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_append_rejects_blank_text_and_writes_nothing(tmp_path, blank):
    with pytest.raises(ValueError):
        prefs(tmp_path).append_line(blank)

    assert not (tmp_path / PREFERENCES_FILE).exists()


@pytest.mark.parametrize(
    ("content", "mode"),
    [
        (None, None),
        ("- uno\n", None),
        ("reply_mode: voice\n", "voice"),
        ("reply_mode: text\n- x\nreply_mode: both\n", "both"),
        ("reply_mode: both\nreply_mode: loud\n", "both"),
        ("reply_mode: loud\n", None),
        ("  reply_mode:   auto  \n", "auto"),
        ("- reply_mode: voice\n", None),
    ],
)
def test_reply_mode_is_the_last_valid_line(tmp_path, content, mode):
    assert prefs(tmp_path, content).reply_mode() == mode


def test_set_reply_mode_appends_when_absent(tmp_path):
    preferences = prefs(tmp_path, "- uno\n")

    preferences.set_reply_mode("text")

    assert text(tmp_path) == "- uno\nreply_mode: text\n"
    assert preferences.reply_mode() == "text"


def test_set_reply_mode_creates_the_file(tmp_path):
    prefs(tmp_path).set_reply_mode("voice")

    assert text(tmp_path) == "reply_mode: voice\n"


def test_set_reply_mode_replaces_every_line_with_one(tmp_path):
    prefs(tmp_path, "- a\nreply_mode: text\n- b\nreply_mode: loud\n").set_reply_mode("both")

    assert text(tmp_path) == "- a\nreply_mode: both\n- b\n"


def test_set_reply_mode_rejects_invalid_modes(tmp_path):
    with pytest.raises(ValueError, match="auto, voice, text, both"):
        prefs(tmp_path, "- a\n").set_reply_mode("loud")

    assert text(tmp_path) == "- a\n"


def test_exact_duplicate_leaves_the_file_byte_identical(tmp_path):
    original = "- Prefiero respuestas cortas\n"
    preferences = prefs(tmp_path, original)

    preferences.append_line("Prefiero respuestas cortas")

    assert text(tmp_path) == original


def test_duplicate_after_whitespace_normalisation_is_ignored(tmp_path):
    preferences = prefs(tmp_path, "- Prefiero respuestas cortas\n")

    preferences.append_line("  Prefiero   respuestas\tcortas ")

    assert text(tmp_path) == "- Prefiero respuestas cortas\n"


def test_different_case_is_appended(tmp_path):
    prefs(tmp_path, "- Prefiero respuestas cortas\n").append_line("prefiero respuestas cortas")

    assert text(tmp_path) == "- Prefiero respuestas cortas\n- prefiero respuestas cortas\n"


def test_different_text_is_appended(tmp_path):
    prefs(tmp_path, "- Prefiero respuestas cortas\n").append_line("Prefiero respuestas largas")

    assert text(tmp_path).splitlines()[-1] == "- Prefiero respuestas largas"


def test_secrets_are_compared_after_masking(tmp_path):
    preferences = prefs(tmp_path, "- mi clave es ***\n")

    preferences.append_line("mi clave es s3cr3t")

    assert text(tmp_path) == "- mi clave es ***\n"


def test_duplicate_of_a_line_without_trailing_newline_does_not_rewrite(tmp_path):
    preferences = prefs(tmp_path, "- uno")

    preferences.append_line("uno")

    assert text(tmp_path) == "- uno"


def test_existing_duplicates_are_left_untouched(tmp_path):
    preferences = prefs(tmp_path, "- uno\n- uno\n")

    preferences.append_line("dos")

    assert text(tmp_path) == "- uno\n- uno\n- dos\n"


def test_reply_mode_line_is_not_a_preference_duplicate(tmp_path):
    preferences = prefs(tmp_path, "reply_mode: voice\n")

    preferences.append_line("reply_mode: voice")

    assert text(tmp_path) == "reply_mode: voice\n- reply_mode: voice\n"
