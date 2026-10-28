"""Real engines on synthetic audio: only with `uv run pytest -m voice` and the voice extra."""

from __future__ import annotations

import pytest

from tests.fixtures.audio.generate import FIXTURES_DIR, read_wav_float32
from tony.core.voice.ports import OUTPUT_SAMPLE_RATE, Utterance
from tony.core.voice.utterances import WINDOW_BYTES

pytestmark = [pytest.mark.voice, pytest.mark.timeout(120)]


@pytest.fixture(autouse=True)
def voice_extra() -> None:
    """Imported here, not at module level, so the default run never loads an engine."""
    for module in ("faster_whisper", "kokoro", "silero_vad"):
        pytest.importorskip(module)


def windows_of(name: str) -> list[bytes]:
    pcm = read_wav_float32(FIXTURES_DIR / name)
    return [pcm[i : i + WINDOW_BYTES] for i in range(0, len(pcm) - WINDOW_BYTES + 1, WINDOW_BYTES)]


def test_silero_classifies_silence_as_no_speech_and_a_tone_as_something() -> None:
    from tony.core.voice.engines.silero import SileroVad

    vad = SileroVad()
    silence = [vad.classify(window) for window in windows_of("silence_1s.wav")]
    vad.reset()
    speech = [vad.classify(window) for window in windows_of("speech_1500ms.wav")]

    assert not any(silence)
    assert isinstance(speech[0], bool)


def test_faster_whisper_transcribes_noise_as_empty_text_in_spanish() -> None:
    from tony.core.voice.engines.faster_whisper import FasterWhisperStt

    stt = FasterWhisperStt("small")
    pcm = read_wav_float32(FIXTURES_DIR / "noise_3s.wav")

    transcript = stt.transcribe(Utterance(pcm=pcm, duration_ms=3_000), "es")

    assert transcript.language == "es" and transcript.duration_ms == 3_000
    assert len(transcript.text) < 40


def test_kokoro_synthesizes_a_spanish_sentence_as_int16_24k_audio() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    tts = KokoroTts("ef_dora")

    chunks = list(tts.synthesize("Buenos días, señor.", "ef_dora"))

    assert chunks and all(chunk.sample_rate == OUTPUT_SAMPLE_RATE for chunk in chunks)
    assert sum(chunk.duration_ms for chunk in chunks) > 500
    assert any(byte != 0 for byte in chunks[0].pcm16)


def test_kokoro_with_an_unknown_voice_fails_at_load_naming_it() -> None:
    from tony.core.voice.engines.kokoro import KokoroTts

    with pytest.raises(RuntimeError, match="kokoro/no_existe"):
        KokoroTts("no_existe")
