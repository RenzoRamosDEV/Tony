from tony.core.voice.ports import WINDOW_MS

END_SILENCE_MS = 700
MAX_UTTERANCE_MS = 30_000


class UtteranceAssembler:
    """Joins VAD-classified windows into one utterance's PCM: it ends after END_SILENCE_MS of
    silence following speech, or is cut at MAX_UTTERANCE_MS; outer silence is trimmed."""

    def __init__(self) -> None:
        self._windows: list[bytes] = []
        self._speech_end = 0

    @property
    def in_speech(self) -> bool:
        return bool(self._windows)

    def push(self, window: bytes, is_speech: bool) -> bytes | None:
        if not self._windows and not is_speech:
            return None
        self._windows.append(window)
        if is_speech:
            self._speech_end = len(self._windows)
        silence_ms = (len(self._windows) - self._speech_end) * WINDOW_MS
        if silence_ms >= END_SILENCE_MS or len(self._windows) * WINDOW_MS >= MAX_UTTERANCE_MS:
            return self._close()
        return None

    def reset(self) -> None:
        self._windows = []
        self._speech_end = 0

    def _close(self) -> bytes:
        pcm = b"".join(self._windows[: self._speech_end])
        self.reset()
        return pcm
