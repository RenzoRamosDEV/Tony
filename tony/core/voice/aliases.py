"""Voice aliases `motor/voz[?clave=valor(&clave=valor)*]`, validated without importing any engine.

A Kokoro voice may be a weighted blend `id*peso(+id*peso)+`; `speed` applies to every
synthesis engine and `lang` (the phonemizer locale) only to Kokoro.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from tony.core.config import VoiceSettings
from tony.core.voice.ports import VoiceConfigError

STT_ENGINE = "faster-whisper"
KOKORO_ENGINE = "kokoro"
PIPER_ENGINE = "piper"
KOKORO_SPANISH_VOICES = ("ef_dora", "em_alex", "em_santa")
PIPER_SPANISH_VOICES = (
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
    KOKORO_ENGINE: KOKORO_SPANISH_VOICES,
    PIPER_ENGINE: PIPER_SPANISH_VOICES,
}
ENGINES_FOR_KEY: dict[str, tuple[str, ...]] = {
    "voice.stt": (STT_ENGINE,),
    "voice.tts": (KOKORO_ENGINE, PIPER_ENGINE),
}
PARAMETERS = ("speed", "lang")
LANGS = ("es-419", "es")
DEFAULT_LANG = "es-419"
SPEED_RANGE = (0.5, 1.5)
WEIGHT_TOLERANCE = 0.01
Invalid = Callable[[str], VoiceConfigError]


@dataclass(frozen=True)
class VoiceAlias:
    engine: str
    voices: tuple[tuple[str, float], ...]
    speed: float = 1.0
    lang: str = DEFAULT_LANG

    @property
    def name(self) -> str:
        """The voice part of the alias: one id, or the blend `id*peso+id*peso`."""
        if len(self.voices) == 1 and self.voices[0][1] == 1.0:
            return self.voices[0][0]
        return "+".join(f"{voice}*{weight:g}" for voice, weight in self.voices)


def parse_alias(alias: str) -> VoiceAlias:
    def invalid(reason: str) -> VoiceConfigError:
        return VoiceConfigError(f"alias de voz '{alias}' inválido; {reason}")

    head, has_query, query = alias.partition("?")
    engine, separator, voice_part = head.partition("/")
    if not separator or engine not in NAMES_BY_ENGINE:
        raise invalid(f"usa motor/voz con motor en: {', '.join(NAMES_BY_ENGINE)}")
    voices = _parse_voices(engine, voice_part, invalid)
    parameters = _parse_query(query, invalid) if has_query else {}
    if parameters and engine == STT_ENGINE:
        raise invalid(f"{STT_ENGINE} no admite parámetros")
    if "lang" in parameters and engine != KOKORO_ENGINE:
        raise invalid(f"el parámetro lang solo se admite en {KOKORO_ENGINE}")
    return VoiceAlias(
        engine,
        voices,
        speed=_parse_speed(parameters.get("speed"), invalid),
        lang=_parse_lang(parameters.get("lang"), invalid),
    )


def _parse_voices(engine: str, voice_part: str, invalid: Invalid) -> tuple[tuple[str, float], ...]:
    names = NAMES_BY_ENGINE[engine]
    is_blend = "+" in voice_part or "*" in voice_part
    if is_blend and engine != KOKORO_ENGINE:
        raise invalid(f"la mezcla de voces solo se admite en {KOKORO_ENGINE}")
    voices = []
    for item in voice_part.split("+"):
        voice, has_weight, weight_text = item.partition("*")
        if voice not in names:
            raise invalid(f"valores válidos de {engine}: {', '.join(names)}")
        voices.append((voice, _parse_number(weight_text, "peso", invalid) if has_weight else 1.0))
    if not math.isclose(sum(w for _, w in voices), 1.0, abs_tol=WEIGHT_TOLERANCE):
        raise invalid("los pesos de la mezcla deben sumar 1")
    return tuple(voices)


def _parse_query(query: str, invalid: Invalid) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for pair in query.split("&"):
        key, has_value, value = pair.partition("=")
        if key not in PARAMETERS:
            raise invalid(f"parámetro '{key}' desconocido; admitidos: {', '.join(PARAMETERS)}")
        if not has_value:
            raise invalid(f"el parámetro {key} necesita un valor ({key}=…)")
        if key in parameters:
            raise invalid(f"parámetro {key} repetido")
        parameters[key] = value
    return parameters


def _parse_speed(text: str | None, invalid: Invalid) -> float:
    if text is None:
        return 1.0
    speed = _parse_number(text, "speed", invalid)
    low, high = SPEED_RANGE
    if not low <= speed <= high:
        raise invalid("speed debe estar entre 0,5 y 1,5")
    return speed


def _parse_lang(text: str | None, invalid: Invalid) -> str:
    if text is None:
        return DEFAULT_LANG
    if text not in LANGS:
        raise invalid(f"lang debe ser {' o '.join(LANGS)}")
    return text


def _parse_number(text: str, label: str, invalid: Invalid) -> float:
    try:
        return float(text)
    except ValueError:
        raise invalid(f"{label} '{text}' no es un número") from None


def validate_voice_settings(settings: VoiceSettings) -> list[str]:
    """One Spanish message per invalid alias, prefixed by its key (`voice.stt`, `voice.tts`)."""
    problems = []
    for key, alias in (("voice.stt", settings.stt), ("voice.tts", settings.tts)):
        problem = alias_problem(key, alias)
        if problem is not None:
            problems.append(f"{key}: {problem}")
    return problems


def alias_problem(key: str, alias: str) -> str | None:
    """Why `alias` cannot configure `key`, or None when it can."""
    try:
        engine = parse_alias(alias).engine
    except VoiceConfigError as exc:
        return str(exc)
    engines = ENGINES_FOR_KEY[key]
    if engine not in engines:
        return f"alias de voz '{alias}' inválido; motores válidos: {', '.join(engines)}"
    return None
