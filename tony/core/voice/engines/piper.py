"""Piper TTS on CPU (onnxruntime): text -> Int16 PCM chunks resampled to 24 kHz.

The voice model is downloaded once from the `rhasspy/piper-voices` repository to the standard
Hugging Face cache; `speed` maps to Piper's `length_scale = 1 / speed`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tony.core.voice.aliases import VoiceAlias
from tony.core.voice.ports import OUTPUT_SAMPLE_RATE, AudioChunk

REPO_ID = "rhasspy/piper-voices"
INT16_SCALE = 32767
MAX_PEAK = 0.98


def model_file(voice: str) -> str:
    """`es_MX-ald-medium` -> `es/es_MX/ald/medium/es_MX-ald-medium.onnx` (the repo layout)."""
    locale, speaker, quality = voice.split("-", 2)
    return f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{voice}.onnx"


def resample(numpy: Any, samples: Any, source_rate: int, target_rate: int) -> Any:
    """Band-limited resampling of one sentence through the FFT (no extra dependency)."""
    if source_rate == target_rate or len(samples) == 0:
        return samples
    target_count = round(len(samples) * target_rate / source_rate)
    spectrum = numpy.fft.rfft(samples)
    return numpy.fft.irfft(spectrum, n=target_count) * (target_count / len(samples))


class PiperTts:
    def __init__(self, alias: VoiceAlias) -> None:
        import numpy
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        self._numpy = numpy
        path = hf_hub_download(REPO_ID, model_file(alias.name))
        hf_hub_download(REPO_ID, f"{model_file(alias.name)}.json")
        self._voice = PiperVoice.load(path)
        self._config = SynthesisConfig(length_scale=1 / alias.speed)

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        for chunk in self._voice.synthesize(text, syn_config=self._config):
            samples = resample(
                self._numpy, chunk.audio_float_array, chunk.sample_rate, OUTPUT_SAMPLE_RATE
            )
            # Piper normalizes each sentence to full scale and the resampler's ringing
            # overshoots it: scaling below full scale sounds cleaner than clipping.
            peak = float(self._numpy.abs(samples).max(initial=0.0))
            if peak > MAX_PEAK:
                samples = samples * (MAX_PEAK / peak)
            pcm16 = (samples * INT16_SCALE).astype(self._numpy.int16).tobytes()
            yield AudioChunk(pcm16=pcm16, sample_rate=OUTPUT_SAMPLE_RATE)
