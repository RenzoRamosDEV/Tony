"""Short acknowledgements ("Un momento, señor.") synthesized once per voice and kept in memory,
so a delegation can be acknowledged the instant it starts, without waiting for the engine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import TTS_LANE
from tony.core.voice.ports import AudioChunk, Tts


class AckCache:
    def __init__(
        self,
        phrases: list[str],
        tts_loader: Callable[[], Tts],
        executor: VoiceExecutor,
        voice: str,
    ) -> None:
        self._phrases = list(phrases)
        self._tts_loader = tts_loader
        self._executor = executor
        self._voice = voice
        self._audio: list[list[AudioChunk]] = []
        self._next = 0
        self._warming: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        return bool(self._audio)

    def warm(self) -> None:
        """Synthesize every phrase in the background, once; a failure leaves it unready."""
        if self._warming is None:
            self._warming = asyncio.create_task(self._synthesize_all())

    def next(self) -> tuple[str, list[AudioChunk]] | None:
        """The next phrase in rotation with its audio, or None while it is not ready."""
        if not self._audio:
            return None
        index = self._next % len(self._audio)
        self._next += 1
        return self._phrases[index], self._audio[index]

    async def aclose(self) -> None:
        if self._warming is not None and not self._warming.done():
            self._warming.cancel()
            await asyncio.gather(self._warming, return_exceptions=True)

    async def _synthesize_all(self) -> None:
        try:
            audio = await self._executor.run_serial(TTS_LANE, self._synthesize_phrases)
        except Exception:  # noqa: BLE001 - without acknowledgements replies are just spoken later
            return
        self._audio = audio

    def _synthesize_phrases(self) -> list[list[AudioChunk]]:
        tts = self._tts_loader()
        return [list(tts.synthesize(phrase, self._voice)) for phrase in self._phrases]
