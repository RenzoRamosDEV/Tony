"""Kokoro TTS (Spanish G2P through espeak-ng): text -> Int16 PCM chunks at 24 kHz."""

from __future__ import annotations

from collections.abc import Iterator

from tony.core.voice.ports import OUTPUT_SAMPLE_RATE, AudioChunk

LANG_CODE_SPANISH = "e"
REPO_ID = "hexgrad/Kokoro-82M"
INT16_SCALE = 32767


class KokoroTts:
    def __init__(self, voice: str) -> None:
        import numpy
        from kokoro import KPipeline

        self._numpy = numpy
        self._pipeline = KPipeline(lang_code=LANG_CODE_SPANISH, repo_id=REPO_ID)
        try:
            self._pipeline.load_voice(voice)
        except Exception as exc:
            raise RuntimeError(f"no se pudo cargar la voz kokoro/{voice}: {exc}") from exc

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        for result in self._pipeline(text, voice=voice):
            audio = result.audio
            if audio is None:
                continue
            samples = audio.detach().cpu().numpy() if hasattr(audio, "numpy") else audio
            clipped = self._numpy.clip(samples, -1.0, 1.0)
            pcm16 = (clipped * INT16_SCALE).astype(self._numpy.int16).tobytes()
            yield AudioChunk(pcm16=pcm16, sample_rate=OUTPUT_SAMPLE_RATE)
