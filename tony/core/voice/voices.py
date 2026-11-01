KOKORO_PREFIX = "kokoro/"


def kokoro_voices(tts: str) -> tuple[str, ...]:
    return tuple(tts.removeprefix(KOKORO_PREFIX).split(","))
