"""Real voice engines behind one registry: lazy, loaded once per process, imported on demand.

The engine modules (`faster_whisper`, `kokoro`, `silero_vad`, `onnxruntime`, `torch`) are
imported inside the default factories, so this package loads without the voice extra and
`voice_availability` can answer with `find_spec` alone.
"""

from __future__ import annotations

import importlib.util
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from tony.core.config import VoiceSettings
from tony.core.voice.aliases import parse_alias, validate_voice_settings
from tony.core.voice.ports import Stt, Tts, Vad

REQUIRED_MODULES = ("faster_whisper", "kokoro", "silero_vad", "onnxruntime", "numpy")
EXTRA_HINT = "instala el extra de voz con `uv sync --extra voice`"
FindSpec = Callable[[str], Any]


@dataclass(frozen=True)
class VoiceAvailability:
    available: bool
    reason: str | None
    stt: str
    tts: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def voice_availability(
    settings: VoiceSettings, find_spec: FindSpec = importlib.util.find_spec
) -> VoiceAvailability:
    missing = [module for module in REQUIRED_MODULES if find_spec(module) is None]
    if missing:
        reason = f"extra tony[voice] no instalado (falta {', '.join(missing)}): {EXTRA_HINT}"
        return VoiceAvailability(False, reason, settings.stt, settings.tts)
    problems = validate_voice_settings(settings)
    if problems:
        return VoiceAvailability(False, "; ".join(problems), settings.stt, settings.tts)
    return VoiceAvailability(True, None, settings.stt, settings.tts)


def load_vad() -> Vad:
    from tony.core.voice.engines.silero import SileroVad

    return SileroVad()


def load_stt(model: str) -> Stt:
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt

    return FasterWhisperStt(model)


def load_tts(voice: str) -> Tts:
    from tony.core.voice.engines.kokoro import KokoroTts

    return KokoroTts(voice)


class EngineRegistry:
    def __init__(
        self,
        settings: VoiceSettings,
        vad_factory: Callable[[], Vad] = load_vad,
        stt_factory: Callable[[str], Stt] = load_stt,
        tts_factory: Callable[[str], Tts] = load_tts,
    ) -> None:
        self.settings = settings
        self._vad_factory = vad_factory
        self._stt_factory = stt_factory
        self._tts_factory = tts_factory
        self._lock = threading.Lock()
        self._vad: Vad | None = None
        self._stt: dict[str, Stt] = {}
        self._tts: dict[str, Tts] = {}

    @property
    def stt_alias(self) -> str:
        return self.settings.stt

    @property
    def tts_alias(self) -> str:
        return self.settings.tts

    @property
    def tts_voice(self) -> str:
        return parse_alias(self.settings.tts)[1]

    def get_vad(self) -> Vad:
        with self._lock:
            if self._vad is None:
                self._vad = self._vad_factory()
            return self._vad

    def get_stt(self, alias: str) -> Stt:
        _, model = parse_alias(alias)
        with self._lock:
            if model not in self._stt:
                self._stt[model] = self._stt_factory(model)
            return self._stt[model]

    def get_tts(self, alias: str) -> Tts:
        _, voice = parse_alias(alias)
        with self._lock:
            if voice not in self._tts:
                self._tts[voice] = self._tts_factory(voice)
            return self._tts[voice]

    def warmup(self) -> dict[str, int]:
        """Load the three configured engines; milliseconds each took, in load order."""
        loaders = {
            "vad": self.get_vad,
            "stt": lambda: self.get_stt(self.settings.stt),
            "tts": lambda: self.get_tts(self.settings.tts),
        }
        timings = {}
        for name, loader in loaders.items():
            started = time.perf_counter()
            loader()
            timings[name] = int((time.perf_counter() - started) * 1_000)
        return timings
