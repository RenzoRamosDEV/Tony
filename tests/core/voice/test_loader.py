import pytest

from tony.core.config.settings import VoiceSettings
from tony.core.voice.engines.loader import EXTRA_MISSING, REQUIRED_MODULES, load_engines
from tony.core.voice.ports import Unavailable


def failing_on(missing, error):
    imported = []

    def importer(name):
        imported.append(name)
        if name == missing:
            raise error
        return object()

    return importer, imported


@pytest.mark.parametrize("missing", ["faster_whisper", "kokoro", "torch", "sounddevice"])
def test_a_missing_package_names_the_voice_extra(missing):
    importer, _ = failing_on(missing, ModuleNotFoundError(f"No module named '{missing}'"))

    outcome = load_engines(VoiceSettings(), ("kokoro/em_alex",), importer=importer)

    assert outcome == Unavailable(EXTRA_MISSING)
    assert "uv sync --extra voice" in EXTRA_MISSING


def test_a_missing_audio_library_names_portaudio():
    importer, _ = failing_on("sounddevice", OSError("PortAudio library not found"))

    outcome = load_engines(VoiceSettings(), ("kokoro/em_alex",), importer=importer)

    assert isinstance(outcome, Unavailable)
    assert "PortAudio library not found" in outcome.reason


def test_every_required_module_is_probed_then_the_engines_are_built():
    importer, imported = failing_on("never", ImportError())
    built = []

    def build(settings, voices):
        built.append((settings, voices))
        return "engines"

    outcome = load_engines(VoiceSettings(), ("kokoro/em_alex",), importer=importer, build=build)

    assert outcome == "engines"
    assert built == [(VoiceSettings(), ("kokoro/em_alex",))]
    assert imported == list(REQUIRED_MODULES)
    assert set(REQUIRED_MODULES) == {
        "numpy",
        "torch",
        "sounddevice",
        "silero_vad",
        "faster_whisper",
        "kokoro",
    }


def test_a_failing_build_is_not_hidden():
    importer, _ = failing_on("never", ImportError())

    def build(settings, voices):
        raise RuntimeError("model download failed")

    with pytest.raises(RuntimeError, match="model download failed"):
        load_engines(VoiceSettings(), (), importer=importer, build=build)
