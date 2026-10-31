"""Tests for tony.core.config (specs/core-config)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tony.core.config import ConfigError, EngineProfile, dotenv_secrets, load_env, load_settings


def write_yaml(tmp_repo: Path, body: str) -> Path:
    path = tmp_repo / "config" / "tony.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_yields_full_defaults(tmp_repo: Path) -> None:
    settings = load_settings(tmp_repo / "config" / "tony.yaml")

    assert settings.front == "jarvis"
    assert settings.worker == "viernes"
    assert settings.reply_mode == "auto"
    assert settings.models == {
        "claude-haiku": "claude-haiku-5-5",
        "claude-sonnet": "claude-sonnet-5-5",
    }
    assert settings.voice.model_dump() == {
        "stt": "faster-whisper/base",
        "tts": "piper/es_MX-ald-medium?speed=0.95",
        "vad": "silero",
        "end_silence_ms": 500,
        "barge_in": True,
        "barge_in_threshold": 0.8,
        "barge_in_min_speech_ms": 280,
        "cpu_threads": None,
        "acknowledgements": [
            "Un momento, señor.",
            "Enseguida, señor.",
            "Ahora mismo lo reviso, señor.",
        ],
    }
    assert settings.channels == ["cli", "web"]
    assert settings.web.model_dump() == {"port": 8787, "host": "127.0.0.1"}
    assert settings.limits.model_dump() == {
        "tool_timeout_s": 20,
        "task_timeout_s": 300,
        "confirm_timeout_s": 60,
        "mcp_connect_timeout_s": 10,
        "token_alert": 50000,
        "memory_max_lines": 200,
    }


def test_none_path_yields_defaults_without_touching_disk() -> None:
    assert load_settings(None).front == "jarvis"


def test_partial_file_overrides_only_given_fields(tmp_repo: Path) -> None:
    settings = load_settings(write_yaml(tmp_repo, "web:\n  port: 9000\n"))

    assert settings.web.port == 9000
    assert settings.web.host == "127.0.0.1"
    assert settings.limits.tool_timeout_s == 20
    assert settings.front == "jarvis"


def test_extra_model_alias_is_merged_with_defaults(tmp_repo: Path) -> None:
    settings = load_settings(write_yaml(tmp_repo, "models:\n  claude-opus: claude-opus-5\n"))

    assert settings.models == {
        "claude-haiku": "claude-haiku-5-5",
        "claude-sonnet": "claude-sonnet-5-5",
        "claude-opus": "claude-opus-5",
    }


def test_file_can_override_default_alias(tmp_repo: Path) -> None:
    settings = load_settings(write_yaml(tmp_repo, "models:\n  claude-haiku: other-id\n"))

    assert settings.models["claude-haiku"] == "other-id"
    assert settings.models["claude-sonnet"] == "claude-sonnet-5-5"


def test_invalid_limit_type_names_field_path(tmp_repo: Path) -> None:
    path = write_yaml(tmp_repo, 'limits:\n  tool_timeout_s: "veinte"\n')

    with pytest.raises(ConfigError) as exc_info:
        load_settings(path)

    assert "limits.tool_timeout_s" in str(exc_info.value)


def test_reply_mode_outside_domain_lists_allowed_values(tmp_repo: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, "reply_mode: loud\n"))

    message = str(exc_info.value)
    assert "reply_mode" in message
    for allowed in ("auto", "voice", "text", "both"):
        assert allowed in message


def test_front_equal_to_worker_is_rejected(tmp_repo: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, "front: viernes\nworker: viernes\n"))

    message = str(exc_info.value)
    assert "front" in message and "worker" in message


def test_swapped_front_and_worker_is_accepted(tmp_repo: Path) -> None:
    settings = load_settings(write_yaml(tmp_repo, "front: viernes\nworker: jarvis\n"))

    assert (settings.front, settings.worker) == ("viernes", "jarvis")


def test_unknown_top_level_key_is_rejected(tmp_repo: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, "colour: blue\n"))

    assert "colour" in str(exc_info.value)


def test_dotenv_value_is_available(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    (tmp_repo / "config" / ".env").write_text("NOTION_TOKEN=abc123\n", encoding="utf-8")

    env = load_env(tmp_repo / "config" / ".env")

    assert env["NOTION_TOKEN"] == "abc123"


def test_process_env_wins_over_dotenv(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME_NOTES", "/b")
    (tmp_repo / "config" / ".env").write_text("HOME_NOTES=/a\n", encoding="utf-8")

    env = load_env(tmp_repo / "config" / ".env")

    assert env["HOME_NOTES"] == "/b"


def test_missing_dotenv_returns_process_env(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONLY_IN_PROCESS", "1")

    env = load_env(tmp_repo / "config" / ".env")

    assert env["ONLY_IN_PROCESS"] == "1"


def test_dotenv_secrets_are_only_file_values(
    tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS_ONLY", "process-value")
    (tmp_repo / "config" / ".env").write_text("A=valor-a\nB=\n", encoding="utf-8")

    assert dotenv_secrets(tmp_repo / "config" / ".env") == ["valor-a"]


def test_dotenv_secrets_of_missing_file_is_empty(tmp_repo: Path) -> None:
    assert dotenv_secrets(tmp_repo / "config" / ".env") == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("- 1\n- 2\n", "config: debe ser un mapa YAML"),
        ("models: null\n", "models: Value error, debe ser un mapa de alias"),
        ("limits: [\n", "YAML inválido"),
    ],
)
def test_malformed_root_or_section_becomes_config_error(
    tmp_repo: Path, body: str, fragment: str
) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, body))

    assert str(exc_info.value).startswith(fragment)


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("end_silence_ms", "299", False),
        ("end_silence_ms", "300", True),
        ("end_silence_ms", "1500", True),
        ("end_silence_ms", "1501", False),
        ("barge_in_threshold", "0.49", False),
        ("barge_in_threshold", "0.5", True),
        ("barge_in_threshold", "0.99", True),
        ("barge_in_threshold", "1.0", False),
        ("barge_in_min_speech_ms", "149", False),
        ("barge_in_min_speech_ms", "150", True),
        ("barge_in_min_speech_ms", "1000", True),
        ("barge_in_min_speech_ms", "1001", False),
        ("cpu_threads", "null", True),
        ("cpu_threads", "0", False),
        ("cpu_threads", "64", True),
        ("cpu_threads", "65", False),
        ("acknowledgements", "[]", False),
        ("acknowledgements", "[" + ", ".join(["Vale."] * 11) + "]", False),
        ("acknowledgements", "[" + ", ".join(["Vale."] * 10) + "]", True),
        ("acknowledgements", '["' + "a" * 61 + '"]', False),
        ("acknowledgements", '["' + "a" * 60 + '"]', True),
        ("acknowledgements", '["Vale.", ""]', False),
        ("acknowledgements", '["Vale.", "   "]', False),
    ],
)
def test_voice_ranges_name_the_field_path(
    tmp_repo: Path, field: str, value: str, valid: bool
) -> None:
    path = write_yaml(tmp_repo, f"voice:\n  {field}: {value}\n")

    if valid:
        load_settings(path)
        return
    with pytest.raises(ConfigError) as exc_info:
        load_settings(path)
    assert f"voice.{field}" in str(exc_info.value)


def test_end_silence_out_of_range_names_the_range(tmp_repo: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, "voice:\n  end_silence_ms: 100\n"))

    assert "voice.end_silence_ms" in str(exc_info.value)
    assert "300" in str(exc_info.value)
    assert "1500" in str(exc_info.value)


def test_claude_sdk_engine_profile_is_always_implicitly_present(tmp_repo: Path) -> None:
    settings = load_settings(tmp_repo / "config" / "tony.yaml")

    assert settings.engines == {"claude_sdk": EngineProfile(type="claude_sdk")}


def test_declared_engine_profiles_merge_with_the_implicit_claude_sdk(tmp_repo: Path) -> None:
    settings = load_settings(
        write_yaml(
            tmp_repo,
            "engines:\n"
            "  gemini:\n"
            "    type: litellm\n"
            "    model: gemini/gemini-2.0-flash\n",
        )
    )

    assert settings.engines == {
        "claude_sdk": EngineProfile(type="claude_sdk"),
        "gemini": EngineProfile(type="litellm", model="gemini/gemini-2.0-flash"),
    }


def test_litellm_profile_without_model_is_rejected(tmp_repo: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_settings(write_yaml(tmp_repo, "engines:\n  gemini:\n    type: litellm\n"))

    message = str(exc_info.value)
    assert "gemini" in message
    assert "model" in message


def test_redeclaring_claude_sdk_profile_overrides_the_implicit_one(tmp_repo: Path) -> None:
    settings = load_settings(
        write_yaml(tmp_repo, "engines:\n  claude_sdk:\n    type: claude_sdk\n")
    )

    assert settings.engines == {"claude_sdk": EngineProfile(type="claude_sdk")}
