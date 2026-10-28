"""Voice aliases `motor/nombre` of voice.stt / voice.tts (specs/voice-engines)."""

from __future__ import annotations

import pytest

from tony.core.config import VoiceSettings
from tony.core.voice.aliases import (
    KOKORO_SPANISH_VOICES,
    WHISPER_MODELS,
    parse_alias,
    validate_voice_settings,
)
from tony.core.voice.ports import VoiceConfigError


def test_parse_alias_splits_engine_and_name() -> None:
    assert parse_alias("kokoro/ef_dora") == ("kokoro", "ef_dora")


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("faster-whisper/small", ("faster-whisper", "small")),
        ("faster-whisper/base", ("faster-whisper", "base")),
        ("faster-whisper/large-v3", ("faster-whisper", "large-v3")),
        ("faster-whisper/distil-large-v3", ("faster-whisper", "distil-large-v3")),
        ("faster-whisper/small.en", ("faster-whisper", "small.en")),
        ("kokoro/em_alex", ("kokoro", "em_alex")),
        ("kokoro/em_santa", ("kokoro", "em_santa")),
    ],
)
def test_known_engines_and_names_are_accepted(alias: str, expected: tuple[str, str]) -> None:
    assert parse_alias(alias) == expected


@pytest.mark.parametrize(
    ("alias", "valid_values"),
    [
        ("kokoro/no_existe", KOKORO_SPANISH_VOICES),
        ("whisper/small", ("faster-whisper", "kokoro")),
        ("kokoro", ("faster-whisper", "kokoro")),
        ("", ("faster-whisper", "kokoro")),
        ("faster-whisper/", WHISPER_MODELS),
        ("faster-whisper/huge", WHISPER_MODELS),
    ],
)
def test_invalid_alias_names_the_alias_and_the_valid_values(
    alias: str, valid_values: tuple[str, ...]
) -> None:
    with pytest.raises(VoiceConfigError) as info:
        parse_alias(alias)

    message = str(info.value)
    assert alias in message
    assert "inválido" in message
    for value in valid_values:
        assert value in message


def test_error_messages_list_the_valid_values_separated_by_commas() -> None:
    with pytest.raises(VoiceConfigError) as info:
        parse_alias("kokoro")
    assert str(info.value) == (
        "alias de voz 'kokoro' inválido; usa motor/nombre con motor en: faster-whisper, kokoro"
    )

    problems = validate_voice_settings(VoiceSettings(tts="faster-whisper/small"))
    assert problems == [
        "voice.tts: alias de voz 'faster-whisper/small' inválido; valores válidos: "
        "kokoro/ef_dora, kokoro/em_alex, kokoro/em_santa"
    ]


def test_both_aliases_invalid_report_two_problems() -> None:
    problems = validate_voice_settings(VoiceSettings(stt="whisper/x", tts="kokoro/nadie"))

    assert [p.split(":")[0] for p in problems] == ["voice.stt", "voice.tts"]


def test_valid_settings_have_no_problems() -> None:
    assert validate_voice_settings(VoiceSettings()) == []


def test_each_invalid_setting_is_reported_with_its_key() -> None:
    settings = VoiceSettings(stt="kokoro/ef_dora", tts="kokoro/no_existe")

    problems = validate_voice_settings(settings)

    assert len(problems) == 2
    assert problems[0].startswith("voice.stt: ") and "faster-whisper/" in problems[0]
    assert problems[1].startswith("voice.tts: ") and "kokoro/no_existe" in problems[1]
    assert "ef_dora, em_alex, em_santa" in problems[1]


def test_tts_alias_must_be_a_kokoro_voice_and_stt_a_whisper_model() -> None:
    swapped = VoiceSettings(stt="faster-whisper/small", tts="faster-whisper/small")

    problems = validate_voice_settings(swapped)

    assert [p.split(":")[0] for p in problems] == ["voice.tts"]
    assert "kokoro/" in problems[0]
