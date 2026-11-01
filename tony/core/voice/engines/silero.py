from tony.core.voice.ports import INPUT_RATE

SPEECH_THRESHOLD = 0.5


class SileroVad:
    def __init__(self) -> None:
        from silero_vad import load_silero_vad

        self._model = load_silero_vad()

    def is_speech(self, window: bytes) -> bool:
        import numpy
        import torch

        samples = torch.from_numpy(numpy.frombuffer(window, dtype=numpy.float32).copy())
        with torch.no_grad():
            return float(self._model(samples, INPUT_RATE)) >= SPEECH_THRESHOLD

    def reset(self) -> None:
        self._model.reset_states()
