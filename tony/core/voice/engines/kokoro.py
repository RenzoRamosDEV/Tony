from typing import Any

from tony.core.voice.engines.faster_whisper import half_the_cores
from tony.core.voice.ports import OUTPUT_RATE, Clip
from tony.core.voice.voices import kokoro_voices

LANG_CODE = "e"
REPO_ID = "hexgrad/Kokoro-82M"


class KokoroTts:
    """One Kokoro pipeline in Spanish; each `voice.tts` value is loaded once, a blend being
    the element-wise mean of its voices."""

    def __init__(self, voices: tuple[str, ...]) -> None:
        from kokoro import KPipeline

        self._pipeline = KPipeline(lang_code=LANG_CODE, repo_id=REPO_ID)
        self._voices: dict[str, Any] = {}
        for voice in voices:
            self.voice_tensor(voice)

    def voice_tensor(self, voice: str) -> Any:
        if voice not in self._voices:
            import torch

            tensors = [self._pipeline.load_voice(name) for name in kokoro_voices(voice)]
            self._voices[voice] = torch.stack(tensors).mean(dim=0)
        return self._voices[voice]

    def synthesize(self, text: str, voice: str) -> Clip:
        import numpy
        import torch

        torch.set_num_threads(half_the_cores())
        parts = [
            result.audio.detach().cpu().numpy()
            for result in self._pipeline(text, voice=self.voice_tensor(voice))
            if result.audio is not None
        ]
        audio = numpy.concatenate(parts) if parts else numpy.zeros(0, dtype=numpy.float32)
        return Clip(audio.astype(numpy.float32).tobytes(), OUTPUT_RATE)
