"""Silero VAD over onnxruntime (CPU): one 512-sample window at 16 kHz -> speech probability."""

from __future__ import annotations

from tony.core.voice.ports import INPUT_SAMPLE_RATE

SPEECH_THRESHOLD = 0.5


class SileroVad:
    def __init__(self) -> None:
        import numpy
        import torch
        from silero_vad import load_silero_vad

        self._numpy = numpy
        self._torch = torch
        self._model = load_silero_vad(onnx=True)

    def classify(self, window: bytes) -> bool:
        samples = self._numpy.frombuffer(window, dtype=self._numpy.float32)
        probability = self._model(self._torch.from_numpy(samples.copy()), INPUT_SAMPLE_RATE)
        return float(probability) >= SPEECH_THRESHOLD

    def reset(self) -> None:
        self._model.reset_states()
