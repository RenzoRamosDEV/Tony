import os

LANGUAGE = "es"


def half_the_cores() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


class FasterWhisperStt:
    """faster-whisper on CPU with int8 weights, greedy decoding, Spanish."""

    def __init__(self, model: str) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model, device="cpu", compute_type="int8", cpu_threads=half_the_cores()
        )

    def transcribe(self, pcm: bytes) -> str:
        import numpy

        segments, _ = self._model.transcribe(
            numpy.frombuffer(pcm, dtype=numpy.float32),
            language=LANGUAGE,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
