"""Real engines on synthetic audio: only with `uv run pytest -m voice` and the voice extra."""

from __future__ import annotations

import pytest

from tests.fixtures.audio.generate import FIXTURES_DIR, read_wav_float32
from tony.core.voice.aliases import VoiceAlias, parse_alias
from tony.core.voice.ports import INPUT_SAMPLE_RATE, OUTPUT_SAMPLE_RATE, AudioChunk, Utterance
from tony.core.voice.utterances import WINDOW_BYTES

pytestmark = [pytest.mark.voice, pytest.mark.timeout(120)]


@pytest.fixture(autouse=True)
def voice_extra() -> None:
    """Imported here, not at module level, so the default run never loads an engine."""
    for module in ("faster_whisper", "kokoro", "piper", "silero_vad"):
        pytest.importorskip(module)


def windows_of(name: str) -> list[bytes]:
    pcm = read_wav_float32(FIXTURES_DIR / name)
    return [pcm[i : i + WINDOW_BYTES] for i in range(0, len(pcm) - WINDOW_BYTES + 1, WINDOW_BYTES)]


def test_silero_classifies_silence_as_no_speech_and_a_tone_as_something() -> None:
    from tony.core.voice.engines.silero import SileroVad

    vad = SileroVad()
    silence = [vad.classify(window, 0.5) for window in windows_of("silence_1s.wav")]
    vad.reset()
    strict = [vad.classify(window, 0.8) for window in windows_of("silence_1s.wav")]
    vad.reset()
    speech = [vad.classify(window, 0.5) for window in windows_of("speech_1500ms.wav")]

    assert not any(silence)
    assert not any(strict)
    assert isinstance(speech[0], bool)


def test_silero_compares_the_probability_with_the_given_threshold() -> None:
    from tony.core.voice.engines.silero import SileroVad

    vad = SileroVad()
    vad._model = lambda samples, rate: 0.6
    window = windows_of("silence_1s.wav")[0]

    assert vad.classify(window, 0.5) is True
    assert vad.classify(window, 0.8) is False


def test_faster_whisper_transcribes_noise_as_empty_text_in_spanish() -> None:
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt

    stt = FasterWhisperStt("base", 4)
    pcm = read_wav_float32(FIXTURES_DIR / "noise_3s.wav")

    transcript = stt.transcribe(Utterance(pcm=pcm, duration_ms=3_000), "es")

    assert transcript.language == "es" and transcript.duration_ms == 3_000
    assert len(transcript.text) < 40


def test_kokoro_synthesizes_a_spanish_sentence_as_int16_24k_audio() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    tts = KokoroTts(parse_alias("kokoro/ef_dora"), 4)

    chunks = list(tts.synthesize("Buenos días, señor.", "ef_dora"))

    assert chunks and all(chunk.sample_rate == OUTPUT_SAMPLE_RATE for chunk in chunks)
    assert sum(chunk.duration_ms for chunk in chunks) > 500
    assert any(byte != 0 for byte in chunks[0].pcm16)


def test_kokoro_with_an_unknown_voice_fails_at_load_naming_it() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    with pytest.raises(RuntimeError, match="kokoro/no_existe"):
        KokoroTts(VoiceAlias("kokoro", (("no_existe", 1.0),)), 4)


def pcm_of(chunks: list[AudioChunk]) -> bytes:
    return b"".join(chunk.pcm16 for chunk in chunks)


def test_piper_synthesizes_at_24k_keeping_the_duration_without_clipping() -> None:
    import time

    import numpy

    from tony.core.voice.engines.piper import PiperTts, resample

    tts = PiperTts(parse_alias("piper/es_MX-ald-medium"))
    native: list = []
    synthesize = tts._voice.synthesize

    def recording(*args, **kwargs):
        for chunk in synthesize(*args, **kwargs):
            native.append(chunk)
            yield chunk

    tts._voice.synthesize = recording
    chunks = list(tts.synthesize("Buenos días, señor.", "es_MX-ald-medium"))

    native_ms = sum(len(c.audio_float_array) for c in native) * 1_000 / native[0].sample_rate
    samples = numpy.frombuffer(pcm_of(chunks), dtype=numpy.int16)
    assert native[0].sample_rate == 22_050
    assert all(chunk.sample_rate == OUTPUT_SAMPLE_RATE for chunk in chunks)
    assert abs(len(samples) * 1_000 / OUTPUT_SAMPLE_RATE - native_ms) / native_ms < 0.01
    assert numpy.abs(samples).max() < 32767
    started = time.perf_counter()
    resample(numpy, native[0].audio_float_array, 22_050, OUTPUT_SAMPLE_RATE)
    assert (time.perf_counter() - started) * 1_000 < 10


def test_kokoro_phonemizes_with_seseo_by_default_and_castilian_on_request() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    latin = KokoroTts(parse_alias("kokoro/em_alex"), 4).phonemize("cielo, zapato")
    castilian = KokoroTts(parse_alias("kokoro/em_alex?lang=es"), 4).phonemize("cielo")

    assert latin.startswith("s") and "θ" not in latin
    assert "θ" in castilian


def test_kokoro_blend_synthesizes_audio() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    tts = KokoroTts(parse_alias("kokoro/em_alex*0.6+em_santa*0.4?speed=0.94"), 4)

    assert any(byte != 0 for byte in pcm_of(list(tts.synthesize("Un momento, señor.", ""))))


def transcribe_spoken(tts, text: str) -> str:
    import numpy

    from tony.core.voice.engines.faster_whisper import FasterWhisperStt
    from tony.core.voice.engines.piper import resample

    speech = numpy.frombuffer(pcm_of(list(tts.synthesize(text, ""))), numpy.int16) / 32768.0
    audio = resample(numpy, speech, OUTPUT_SAMPLE_RATE, INPUT_SAMPLE_RATE).astype(numpy.float32)
    utterance = Utterance(audio.tobytes(), len(audio) * 1_000 // INPUT_SAMPLE_RATE)
    return FasterWhisperStt("base", 4).transcribe(utterance, "es").text.lower()


def test_whisper_base_transcribes_a_spoken_question() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    tts = KokoroTts(parse_alias("kokoro/em_alex"), 4)

    assert "qué hora es" in transcribe_spoken(tts, "¿Qué hora es?")


def test_whisper_base_understands_the_default_piper_voice() -> None:
    from tony.core.voice.engines.piper import PiperTts

    tts = PiperTts(parse_alias("piper/es_MX-ald-medium?speed=0.95"))

    assert "un momento" in transcribe_spoken(tts, "Un momento, señor.")
