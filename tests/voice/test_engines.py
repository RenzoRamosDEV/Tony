"""Real voice engines (uv sync --extra voice; uv run pytest -m voice)."""

import pytest

pytestmark = pytest.mark.voice

numpy = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from tony.core.voice.ports import INPUT_RATE, OUTPUT_RATE, WINDOW_BYTES, Clip  # noqa: E402

VOICES = ("kokoro/em_alex", "kokoro/ef_dora", "kokoro/ef_dora,bf_emma")


@pytest.fixture(scope="module")
def tts():
    from tony.core.voice.engines.kokoro import KokoroTts

    return KokoroTts(VOICES)


@pytest.fixture(scope="module")
def question(tts):
    return to_input_rate(tts.synthesize("¿Qué hora es?", "kokoro/em_alex"))


def to_input_rate(clip: Clip) -> bytes:
    samples = numpy.frombuffer(clip.pcm, dtype=numpy.float32)
    positions = numpy.arange(0, len(samples), clip.rate / INPUT_RATE)
    return numpy.interp(positions, numpy.arange(len(samples)), samples).astype("float32").tobytes()


def windows(pcm: bytes):
    return [pcm[i : i + WINDOW_BYTES] for i in range(0, len(pcm) - WINDOW_BYTES + 1, WINDOW_BYTES)]


@pytest.mark.parametrize("voice", VOICES)
def test_kokoro_synthesises_audio_at_24_khz(tts, voice):
    clip = tts.synthesize("Buenas tardes, señor.", voice)
    assert clip.rate == OUTPUT_RATE and len(clip.pcm) > OUTPUT_RATE


def test_kokoro_blend_is_the_mean_of_its_voices(tts):
    blend = tts.voice_tensor("kokoro/ef_dora,bf_emma")
    expected = (tts.voice_tensor("kokoro/ef_dora") + tts.voice_tensor("kokoro/bf_emma")) / 2
    assert torch.allclose(blend, expected)


def test_silero_detects_speech_but_not_silence(question):
    from tony.core.voice.engines.silero import SileroVad

    vad = SileroVad()
    assert any(vad.is_speech(window) for window in windows(question))
    vad.reset()
    silence = bytes(WINDOW_BYTES * 30)
    assert not any(vad.is_speech(window) for window in windows(silence))


def test_faster_whisper_transcribes_a_kokoro_question(question):
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt

    assert "hora" in FasterWhisperStt("small").transcribe(question).lower()


def test_load_engines_builds_every_engine():
    from tony.core.config.settings import VoiceSettings
    from tony.core.voice.engines.loader import load_engines
    from tony.core.voice.ports import Engines

    assert isinstance(load_engines(VoiceSettings(), VOICES[:1]), Engines)


def _has_device(kind: str) -> bool:
    sounddevice = pytest.importorskip("sounddevice")
    try:
        sounddevice.query_devices(kind=kind)
    except Exception:
        return False
    return True


def test_sounddevice_input_delivers_16_khz_float32_mono_windows():
    if not _has_device("input"):
        pytest.skip("no input device")
    import threading

    from tony.core.voice.engines.sounddevice_io import SoundDeviceInput

    got, done = [], threading.Event()

    def on_frame(frame):
        got.append(frame)
        done.set()

    audio = SoundDeviceInput()
    audio.open(on_frame)
    try:
        assert done.wait(5)
    finally:
        audio.close()
    assert len(got[0]) == WINDOW_BYTES


def test_sounddevice_output_plays_a_silent_clip():
    if not _has_device("output"):
        pytest.skip("no output device")
    from tony.core.voice.engines.sounddevice_io import SoundDeviceOutput

    SoundDeviceOutput().play(Clip(bytes(4 * OUTPUT_RATE // 10)))
