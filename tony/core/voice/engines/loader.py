import importlib
from collections.abc import Callable
from typing import Any

from tony.core.config.settings import VoiceSettings
from tony.core.voice.ports import Engines, Unavailable

EXTRA_MISSING = "voice extra not installed: uv sync --extra voice"
REQUIRED_MODULES = ("numpy", "torch", "sounddevice", "silero_vad", "faster_whisper", "kokoro")

Build = Callable[[VoiceSettings, tuple[str, ...]], Engines]


def build_engines(settings: VoiceSettings, voices: tuple[str, ...]) -> Engines:
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt
    from tony.core.voice.engines.kokoro import KokoroTts
    from tony.core.voice.engines.silero import SileroVad
    from tony.core.voice.engines.sounddevice_io import SoundDeviceInput, SoundDeviceOutput

    return Engines(
        audio_input=SoundDeviceInput(device=settings.input_device),
        audio_output=SoundDeviceOutput(device=settings.output_device),
        vad=SileroVad(),
        stt=FasterWhisperStt(settings.stt.split("/", 1)[1]),
        tts=KokoroTts(voices),
    )


def load_engines(
    settings: VoiceSettings,
    voices: tuple[str, ...],
    *,
    importer: Callable[[str], Any] = importlib.import_module,
    build: Build = build_engines,
) -> Engines | Unavailable:
    """Load the real engines, or say why voice is unavailable when the extra is missing."""
    for module in REQUIRED_MODULES:
        try:
            importer(module)
        except ImportError:
            return Unavailable(EXTRA_MISSING)
        except OSError as error:
            return Unavailable(f"audio library unavailable (install PortAudio): {error}")
    return build(settings, voices)
