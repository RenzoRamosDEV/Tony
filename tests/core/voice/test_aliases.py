"""Voice aliases `motor/voz[?clave=valor]` of voice.stt / voice.tts (specs/voice-engines)."""

from __future__ import annotations

import pytest

from tony.core.config import VoiceSettings
from tony.core.voice.aliases import (
    KOKORO_SPANISH_VOICES,
    PIPER_SPANISH_VOICES,
    WHISPER_MODELS,
    VoiceAlias,
    parse_alias,
    validate_voice_settings,
)
from tony.core.voice.ports import VoiceConfigError


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("kokoro/ef_dora", VoiceAlias("kokoro", (("ef_dora", 1.0),), speed=1.0, lang="es-419")),
        (
            "piper/es_MX-ald-medium?speed=0.95",
            VoiceAlias("piper", (("es_MX-ald-medium", 1.0),), speed=0.95, lang="es-419"),
        ),
        (
            "kokoro/em_alex*0.6+em_santa*0.4?speed=0.94&lang=es",
            VoiceAlias("kokoro", (("em_alex", 0.6), ("em_santa", 0.4)), speed=0.94, lang="es"),
        ),
        ("faster-whisper/base", VoiceAlias("faster-whisper", (("base", 1.0),))),
        (
            "faster-whisper/distil-large-v3",
            VoiceAlias("faster-whisper", (("distil-large-v3", 1.0),)),
        ),
        ("kokoro/em_santa?lang=es-419", VoiceAlias("kokoro", (("em_santa", 1.0),))),
        (
            "piper/es_MX-ald-medium?speed=0.5",
            VoiceAlias("piper", (("es_MX-ald-medium", 1.0),), 0.5),
        ),
        (
            "piper/es_MX-ald-medium?speed=1.5",
            VoiceAlias("piper", (("es_MX-ald-medium", 1.0),), 1.5),
        ),
        (
            "kokoro/em_alex*0.6+em_santa*0.395",
            VoiceAlias("kokoro", (("em_alex", 0.6), ("em_santa", 0.395))),
        ),
    ],
)
def test_valid_aliases_parse_to_voice_alias(alias: str, expected: VoiceAlias) -> None:
    assert parse_alias(alias) == expected


def test_voice_alias_name_is_the_voice_part() -> None:
    assert parse_alias("kokoro/ef_dora").name == "ef_dora"
    assert parse_alias("piper/es_MX-ald-medium?speed=0.95").name == "es_MX-ald-medium"
    assert parse_alias("kokoro/em_alex*0.6+em_santa*0.4").name == "em_alex*0.6+em_santa*0.4"


@pytest.mark.parametrize(
    ("alias", "fragments"),
    [
        ("kokoro/no_existe", KOKORO_SPANISH_VOICES),
        ("piper/es_XX-nadie-low", PIPER_SPANISH_VOICES),
        ("whisper/small", ("faster-whisper", "kokoro", "piper")),
        ("kokoro", ("faster-whisper", "kokoro", "piper")),
        ("", ("faster-whisper", "kokoro", "piper")),
        ("faster-whisper/", WHISPER_MODELS),
        ("faster-whisper/huge", WHISPER_MODELS),
        ("piper/es_MX-ald-medium?pitch=2", ("pitch", "speed", "lang")),
        ("piper/es_MX-ald-medium?speed=0.49", ("0,5", "1,5")),
        ("piper/es_MX-ald-medium?speed=1.51", ("0,5", "1,5")),
        ("piper/es_MX-ald-medium?speed=2", ("0,5", "1,5")),
        ("piper/es_MX-ald-medium?speed=rápido", ("speed",)),
        ("kokoro/em_alex*0.6+em_santa*0.6", ("sumar 1",)),
        ("kokoro/em_alex*x+em_santa*0.4", ("peso",)),
        ("kokoro/em_alex*0.6+nadie*0.4", KOKORO_SPANISH_VOICES),
        ("kokoro/em_alex?lang=fr", ("lang", "es-419", "es")),
        ("piper/es_MX-ald-medium?lang=es", ("lang", "kokoro")),
        ("piper/es_MX-ald-medium*0.5+es_MX-claude-high*0.5", ("mezcla", "kokoro")),
        ("kokoro/em_alex?speed=0.9&speed=1.0", ("speed", "repetido")),
        ("kokoro/em_alex?speed", ("speed",)),
        ("faster-whisper/base?speed=1.0", ("faster-whisper", "parámetros")),
    ],
)
def test_invalid_alias_names_the_alias_and_explains(alias: str, fragments: tuple[str, ...]) -> None:
    with pytest.raises(VoiceConfigError) as info:
        parse_alias(alias)

    message = str(info.value)
    assert f"alias de voz '{alias}' inválido" in message
    for fragment in fragments:
        assert fragment in message


def test_engine_error_lists_the_engines_separated_by_commas() -> None:
    with pytest.raises(VoiceConfigError) as info:
        parse_alias("kokoro")

    assert str(info.value) == (
        "alias de voz 'kokoro' inválido; usa motor/voz con motor en: faster-whisper, kokoro, piper"
    )


def test_both_aliases_invalid_report_two_problems() -> None:
    problems = validate_voice_settings(VoiceSettings(stt="whisper/x", tts="kokoro/nadie"))

    assert [p.split(":")[0] for p in problems] == ["voice.stt", "voice.tts"]


def test_default_and_legacy_settings_have_no_problems() -> None:
    assert validate_voice_settings(VoiceSettings()) == []
    assert (
        validate_voice_settings(VoiceSettings(stt="faster-whisper/small", tts="kokoro/ef_dora"))
        == []
    )


def test_each_invalid_setting_is_reported_with_its_key() -> None:
    settings = VoiceSettings(stt="kokoro/ef_dora", tts="kokoro/no_existe")

    problems = validate_voice_settings(settings)

    assert len(problems) == 2
    assert problems[0] == (
        "voice.stt: alias de voz 'kokoro/ef_dora' inválido; motores válidos: faster-whisper"
    )
    assert problems[1].startswith("voice.tts: ") and "kokoro/no_existe" in problems[1]
    assert "ef_dora, em_alex, em_santa" in problems[1]


def test_tts_alias_must_be_a_synthesis_engine() -> None:
    swapped = VoiceSettings(stt="faster-whisper/small", tts="faster-whisper/small")

    problems = validate_voice_settings(swapped)

    assert problems == [
        "voice.tts: alias de voz 'faster-whisper/small' inválido; motores válidos: kokoro, piper"
    ]


def test_piper_catalog_is_the_spanish_index() -> None:
    assert PIPER_SPANISH_VOICES == (
        "es_AR-daniela-high",
        "es_ES-carlfm-x_low",
        "es_ES-davefx-medium",
        "es_ES-mls_10246-low",
        "es_ES-mls_9972-low",
        "es_ES-sharvard-medium",
        "es_MX-ald-medium",
        "es_MX-ald-x_low",
        "es_MX-claude-high",
    )


@pytest.mark.parametrize(
    ("alias", "reason"),
    [
        ("kokoro/em_alex*0.6+em_santa*0.6", "los pesos de la mezcla deben sumar 1"),
        ("piper/es_MX-ald-medium?speed=2", "speed debe estar entre 0,5 y 1,5"),
        ("piper/es_MX-ald-medium?speed=x", "speed 'x' no es un número"),
        ("piper/es_MX-ald-medium?speed=1=2", "speed '1=2' no es un número"),
        ("kokoro/em_alex*x", "peso 'x' no es un número"),
        ("kokoro/em_alex?lang=fr", "lang debe ser es-419 o es"),
        ("kokoro/em_alex?pitch=2", "parámetro 'pitch' desconocido; admitidos: speed, lang"),
        ("kokoro/em_alex?speed", "el parámetro speed necesita un valor (speed=…)"),
        ("piper/es_MX-ald-medium*1.0", "la mezcla de voces solo se admite en kokoro"),
        ("piper/es_MX-ald-medium+es_MX-claude-high", "la mezcla de voces solo se admite en kokoro"),
        ("kokoro/em_alex/x", "valores válidos de kokoro: ef_dora, em_alex, em_santa"),
    ],
)
def test_invalid_alias_messages_are_exact(alias: str, reason: str) -> None:
    with pytest.raises(VoiceConfigError) as info:
        parse_alias(alias)

    assert str(info.value) == f"alias de voz '{alias}' inválido; {reason}"
