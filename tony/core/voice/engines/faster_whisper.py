"""faster-whisper on CPU with int8 weights: one utterance -> one transcript."""

from __future__ import annotations

from tony.core.voice.ports import Transcript, Utterance

CPU_THREADS = 4


class FasterWhisperStt:
    def __init__(self, model: str) -> None:
        import numpy
        from faster_whisper import WhisperModel

        self._numpy = numpy
        self._model = WhisperModel(
            model, device="cpu", compute_type="int8", cpu_threads=CPU_THREADS
        )

    def transcribe(self, utterance: Utterance, language: str) -> Transcript:
        audio = self._numpy.frombuffer(utterance.pcm, dtype=self._numpy.float32)
        segments, _ = self._model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Transcript(text, language, utterance.duration_ms)
