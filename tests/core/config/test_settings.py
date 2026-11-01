import pytest

from tony.core.config.errors import DefinitionError
from tony.core.config.settings import TonyConfig, load_config

DEFAULTS = {
    "front": "jarvis",
    "worker": "viernes",
    "guard": "edith",
    "reply_mode": "auto",
    "models": {"claude-haiku": "claude-haiku-5-5", "claude-sonnet": "claude-sonnet-5-5"},
    "voice": {"stt": "faster-whisper/small", "vad": "silero", "tts_default": "kokoro/em_alex"},
    "desktop": {"hotkey": "Super+J", "tray": True, "theme": "system"},
}


def write_config(root, text):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "tony.yaml").write_text(text)


def test_missing_file_uses_defaults(tmp_path):
    assert load_config(tmp_path).model_dump() == DEFAULTS


@pytest.mark.parametrize("text", ["", "# solo comentarios\n"])
def test_empty_file_uses_defaults(tmp_path, text):
    write_config(tmp_path, text)

    assert load_config(tmp_path).model_dump() == DEFAULTS


def test_partial_file_merges_with_defaults(tmp_path):
    write_config(tmp_path, "reply_mode: text\n")

    assert load_config(tmp_path).model_dump() == {**DEFAULTS, "reply_mode": "text"}


def test_partial_nested_section_keeps_other_nested_defaults(tmp_path):
    write_config(tmp_path, "desktop:\n  tray: false\n")

    assert load_config(tmp_path).desktop.model_dump() == {
        "hotkey": "Super+J", "tray": False, "theme": "system",
    }


@pytest.mark.parametrize("mode", ["auto", "voice", "text", "both"])
def test_accepts_every_reply_mode(tmp_path, mode):
    write_config(tmp_path, f"reply_mode: {mode}\n")

    assert load_config(tmp_path).reply_mode == mode


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("reply_mode: loud\n", "reply_mode"),
        ("engine: litellm\n", "engine"),
        ("voice:\n  tts: x\n", "voice.tts"),
        ("models: [a]\n", "models"),
    ],
)
def test_invalid_content_names_file_and_field(tmp_path, text, field):
    write_config(tmp_path, text)

    with pytest.raises(DefinitionError) as info:
        load_config(tmp_path)

    assert (info.value.file, info.value.field) == ("config/tony.yaml", field)
    assert "config/tony.yaml" in str(info.value) and field in str(info.value)


@pytest.mark.parametrize("text", ["reply_mode: [unclosed\n", "- just\n- a list\n"])
def test_malformed_yaml_names_file(tmp_path, text):
    write_config(tmp_path, text)

    with pytest.raises(DefinitionError) as info:
        load_config(tmp_path)

    assert info.value.file == "config/tony.yaml"


def test_default_instance_matches_documented_defaults():
    assert TonyConfig().model_dump() == DEFAULTS


def test_definition_error_message_format():
    error = DefinitionError("a/b.md", "x.y", "boom")

    assert str(error) == "a/b.md: x.y: boom"


def test_definition_error_without_field():
    assert str(DefinitionError("a/b.md", None, "boom")) == "a/b.md: boom"
