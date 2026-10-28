"""Kokoro TTS: text -> Int16 PCM chunks at 24 kHz, with voice blends, speed and a Latin
American (seseo) espeak phonemizer by default."""

from __future__ import annotations

from collections.abc import Iterator

from tony.core.voice.aliases import VoiceAlias
from tony.core.voice.ports import OUTPUT_SAMPLE_RATE, AudioChunk

LANG_CODE_SPANISH = "e"
REPO_ID = "hexgrad/Kokoro-82M"
INT16_SCALE = 32767


class KokoroTts:
    def __init__(self, alias: VoiceAlias, cpu_threads: int) -> None:
        import numpy
        import torch
        from kokoro import KPipeline
        from misaki.espeak import EspeakG2P

        self._numpy = numpy
        self._torch = torch
        self._cpu_threads = cpu_threads
        self._speed = alias.speed
        self._pipeline = KPipeline(lang_code=LANG_CODE_SPANISH, repo_id=REPO_ID)
        # KPipeline pins `es` (Castilian, with θ) for lang_code "e"; the alias picks the locale.
        self._pipeline.g2p = EspeakG2P(language=alias.lang)
        try:
            self._voice = sum(
                self._pipeline.load_voice(voice) * weight for voice, weight in alias.voices
            )
        except Exception as exc:
            raise RuntimeError(f"no se pudo cargar la voz kokoro/{alias.name}: {exc}") from exc

    def phonemize(self, text: str) -> str:
        return self._pipeline.g2p(text)[0]

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        # torch's intra-op pool is configured per calling thread: set it on the TTS lane thread.
        self._torch.set_num_threads(self._cpu_threads)
        for result in self._pipeline(text, voice=self._voice, speed=self._speed):
            audio = result.audio
            if audio is None:
                continue
            samples = audio.detach().cpu().numpy() if hasattr(audio, "numpy") else audio
            clipped = self._numpy.clip(samples, -1.0, 1.0)
            pcm16 = (clipped * INT16_SCALE).astype(self._numpy.int16).tobytes()
            yield AudioChunk(pcm16=pcm16, sample_rate=OUTPUT_SAMPLE_RATE)
