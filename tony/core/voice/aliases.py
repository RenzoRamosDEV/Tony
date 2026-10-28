"""Aliases `motor/nombre` of voice.stt and voice.tts, validated without importing any engine."""

from __future__ import annotations

from tony.core.config import VoiceSettings
from tony.core.voice.ports import VoiceConfigError

STT_ENGINE = "faster-whisper"
TTS_ENGINE = "kokoro"
KOKORO_SPANISH_VOICES = ("ef_dora", "em_alex", "em_santa")
WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3")
WHISPER_MODELS = (
    *WHISPER_SIZES,
    *(f"{size}.en" for size in WHISPER_SIZES if size != "large-v3"),
    "distil-large-v3",
    "distil-small.en",
    "distil-medium.en",
)
NAMES_BY_ENGINE: dict[str, tuple[str, ...]] = {
    STT_ENGINE: WHISPER_MODELS,
    TTS_ENGINE: KOKORO_SPANISH_VOICES,
}
ENGINE_FOR_KEY = {"voice.stt": STT_ENGINE, "voice.tts": TTS_ENGINE}


def parse_alias(alias: str) -> tuple[str, str]:
    engine, separator, name = alias.partition("/")
    if not separator or engine not in NAMES_BY_ENGINE:
        raise VoiceConfigError(
            f"alias de voz '{alias}' inválido; usa motor/nombre con motor en: "
            f"{', '.join(NAMES_BY_ENGINE)}"
        )
    if name not in NAMES_BY_ENGINE[engine]:
        raise VoiceConfigError(
            f"alias de voz '{alias}' inválido; valores válidos de {engine}: "
            f"{', '.join(NAMES_BY_ENGINE[engine])}"
        )
    return engine, name


def validate_voice_settings(settings: VoiceSettings) -> list[str]:
    """One Spanish message per invalid alias, prefixed by its key (`voice.stt`, `voice.tts`)."""
    problems = []
    for key, expected_engine in ENGINE_FOR_KEY.items():
        alias = getattr(settings, key.split(".")[1])
        try:
            engine, _ = parse_alias(alias)
        except VoiceConfigError as exc:
            problems.append(f"{key}: {exc}")
            continue
        if engine != expected_engine:
            problems.append(
                f"{key}: alias de voz '{alias}' inválido; valores válidos: "
                f"{', '.join(f'{expected_engine}/{n}' for n in NAMES_BY_ENGINE[expected_engine])}"
            )
    return problems
