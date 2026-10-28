"""Real voice engines behind one registry: lazy, loaded once per process, imported on demand.

The engine modules (`faster_whisper`, `kokoro`, `piper`, `silero_vad`, `onnxruntime`, `torch`) are
imported inside the default factories, so this package loads without the voice extra and
`voice_availability` can answer with `find_spec` alone.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from tony.core.config import VoiceSettings
from tony.core.voice.aliases import VoiceAlias, parse_alias, validate_voice_settings
from tony.core.voice.ports import Stt, Tts, Vad

REQUIRED_MODULES = ("faster_whisper", "silero_vad", "onnxruntime", "numpy")
TTS_MODULES = {"kokoro": "kokoro", "piper": "piper"}
EXTRA_HINT = "instala el extra de voz con `uv sync --extra voice`"
FindSpec = Callable[[str], Any]
EngineFactory = Callable[[VoiceAlias, int], Any]


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
    tts_module = TTS_MODULES.get(settings.tts.partition("/")[0])
    modules = (*REQUIRED_MODULES, *((tts_module,) if tts_module else ()))
    missing = [module for module in modules if find_spec(module) is None]
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


def load_stt(alias: VoiceAlias, cpu_threads: int) -> Stt:
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt

    return FasterWhisperStt(alias.name, cpu_threads)


def load_kokoro(alias: VoiceAlias, cpu_threads: int) -> Tts:
    from tony.core.voice.engines.kokoro import KokoroTts

    return KokoroTts(alias, cpu_threads)


def load_piper(alias: VoiceAlias, cpu_threads: int) -> Tts:
    from tony.core.voice.engines.piper import PiperTts

    return PiperTts(alias)


TTS_LOADERS: dict[str, EngineFactory] = {"kokoro": load_kokoro, "piper": load_piper}


def load_tts(alias: VoiceAlias, cpu_threads: int) -> Tts:
    return TTS_LOADERS[alias.engine](alias, cpu_threads)


def default_cpu_threads(cpu_count: Callable[[], int | None] = os.cpu_count) -> int:
    """Half of the logical cores, so STT and TTS leave room for each other and the loop."""
    return max(1, (cpu_count() or 1) // 2)


class EngineRegistry:
    def __init__(
        self,
        settings: VoiceSettings,
        vad_factory: Callable[[], Vad] = load_vad,
        stt_factory: Callable[[VoiceAlias, int], Stt] = load_stt,
        tts_factory: Callable[[VoiceAlias, int], Tts] = load_tts,
        cpu_count: Callable[[], int | None] = os.cpu_count,
    ) -> None:
        self.settings = settings
        self._vad_factory = vad_factory
        self._stt_factory = stt_factory
        self._tts_factory = tts_factory
        self.cpu_threads = settings.cpu_threads or default_cpu_threads(cpu_count)
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
        return parse_alias(self.settings.tts).name

    def get_vad(self) -> Vad:
        with self._lock:
            if self._vad is None:
                self._vad = self._vad_factory()
            return self._vad

    def get_stt(self, alias: str) -> Stt:
        parsed = parse_alias(alias)
        with self._lock:
            if alias not in self._stt:
                self._stt[alias] = self._stt_factory(parsed, self.cpu_threads)
            return self._stt[alias]

    def get_tts(self, alias: str) -> Tts:
        parsed = parse_alias(alias)
        with self._lock:
            if alias not in self._tts:
                self._tts[alias] = self._tts_factory(parsed, self.cpu_threads)
            return self._tts[alias]

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
