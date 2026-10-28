"""Streaming roundtrip of `tony voice bench`: spoken question -> real VAD/STT -> front turn
streaming speech -> first synthesized chunk, measured from the end of the speech."""

from __future__ import annotations

import asyncio
import math
import time
from array import array
from dataclasses import dataclass, field

from tony.apps.web.audio_ws import AudioSession
from tony.core.channels.bootstrap import RuntimeOptions, build_chat_runtime
from tony.core.channels.ports import AssistantReply, AssistantSpeechDelta, ChannelMessage
from tony.core.voice.cleanup import speech_text_for
from tony.core.voice.engines import EngineRegistry
from tony.core.voice.executor import VoiceExecutor
from tony.core.voice.pipeline import SpeechPipeline
from tony.core.voice.ports import (
    INPUT_SAMPLE_RATE,
    AudioChunk,
    Stt,
    Transcript,
    Tts,
    Utterance,
)
from tony.core.voice.segmenter import SentenceSegmenter
from tony.core.voice.utterances import WINDOW_BYTES, WINDOW_MS

QUESTION = "Dime la hora, por favor."
WARMUP_PROMPT = "Hola, Jarvis."
TRAILING_SILENCE_MS = 1_000
SPEECH_RMS = 0.01
FIRST_AUDIO_TIMEOUT_S = 60.0
INT16_FULL_SCALE = 32768.0


@dataclass(frozen=True)
class StreamSample:
    total_ms: int
    endpoint_ms: int
    stt_ms: int
    ttft_ms: int
    tts_first_ms: int


def spoken_utterance(tts: Tts, voice: str, text: str) -> Utterance:
    """`text` spoken by `tts` as the microphone would deliver it: Float32 at 16 kHz."""
    chunks = list(tts.synthesize(text, voice))
    samples = array("h")
    for chunk in chunks:
        samples.frombytes(chunk.pcm16)
    source_rate = chunks[0].sample_rate if chunks else INPUT_SAMPLE_RATE
    resampled = _resample(samples, source_rate, INPUT_SAMPLE_RATE)
    return Utterance(resampled.tobytes(), len(resampled) * 1_000 // INPUT_SAMPLE_RATE)


def _resample(samples: array, source_rate: int, target_rate: int) -> array:
    """Linear interpolation of Int16 samples into Float32 in [-1, 1]."""
    count = len(samples) * target_rate // source_rate
    out = array("f", bytes(4 * count))
    for index in range(count):
        position = index * source_rate / target_rate
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        value = samples[left] * (1 - weight) + samples[right] * weight
        out[index] = value / INT16_FULL_SCALE
    return out


def last_speech_window(pcm: bytes) -> int:
    """Index of the last VAD window whose energy looks like speech."""
    last = 0
    for index in range(len(pcm) // WINDOW_BYTES):
        window = array("f", pcm[index * WINDOW_BYTES : (index + 1) * WINDOW_BYTES])
        if math.sqrt(sum(v * v for v in window) / len(window)) > SPEECH_RMS:
            last = index
    return last


@dataclass
class _Marks:
    end_of_speech: float | None = None
    stt_start: float | None = None
    stt_end: float | None = None
    first_speech: float | None = None
    first_audio: float | None = None
    audio: asyncio.Event = field(default_factory=asyncio.Event)

    def sample(self) -> StreamSample | None:
        if None in (self.end_of_speech, self.stt_start, self.stt_end, self.first_audio):
            return None
        assert self.end_of_speech and self.stt_start and self.stt_end and self.first_audio
        first_speech = self.first_speech or self.first_audio
        return StreamSample(
            total_ms=_ms(self.first_audio - self.end_of_speech),
            endpoint_ms=_ms(self.stt_start - self.end_of_speech),
            stt_ms=_ms(self.stt_end - self.stt_start),
            ttft_ms=_ms(first_speech - self.stt_end),
            tts_first_ms=_ms(self.first_audio - first_speech),
        )


def _ms(seconds: float) -> int:
    return int(seconds * 1_000)


class _TimedStt:
    def __init__(self, inner: Stt, marks: _Marks) -> None:
        self._inner = inner
        self._marks = marks

    def transcribe(self, utterance: Utterance, language: str) -> Transcript:
        self._marks.stt_start = time.perf_counter()
        transcript = self._inner.transcribe(utterance, language)
        self._marks.stt_end = time.perf_counter()
        return transcript


class _FirstAudioSink:
    def __init__(self, marks: _Marks) -> None:
        self._marks = marks

    async def start(self) -> None:
        return None

    async def chunk(self, seq: int, sentence_index: int, audio: AudioChunk) -> None:
        if self._marks.first_audio is None:
            self._marks.first_audio = time.perf_counter()
            self._marks.audio.set()

    async def end(self) -> None:
        return None

    async def cancelled(self) -> None:
        return None

    async def failed(self, error: str) -> None:
        return None


class _SpeakingChannel:
    """Speaks the streamed reply like the web channel does, recording when it starts."""

    def __init__(self, pipeline: SpeechPipeline, marks: _Marks) -> None:
        self._pipeline = pipeline
        self._marks = marks
        self.finishing: asyncio.Task[None] | None = None

    async def send(self, message: ChannelMessage) -> None:
        if isinstance(message, AssistantSpeechDelta):
            if self._marks.first_speech is None:
                self._marks.first_speech = time.perf_counter()
            self._pipeline.feed(message.text)
        elif isinstance(message, AssistantReply) and message.mode != "text":
            if self._marks.first_speech is None:
                self._marks.first_speech = time.perf_counter()
                self._pipeline.feed(speech_text_for(message.display_text, message.speech_text).text)
            self.finishing = asyncio.ensure_future(self._pipeline.finish())


def measure_stream_roundtrip(config, agents_dir, registry: EngineRegistry) -> StreamSample | None:
    return asyncio.run(_stream_roundtrip(config, agents_dir, registry))


async def _stream_roundtrip(config, agents_dir, registry: EngineRegistry) -> StreamSample | None:
    tts_loader = lambda: registry.get_tts(registry.tts_alias)  # noqa: E731
    question = spoken_utterance(tts_loader(), registry.tts_voice, QUESTION).pcm
    microphone = question + bytes(INPUT_SAMPLE_RATE * TRAILING_SILENCE_MS // 1_000 * 4)
    last_speech = last_speech_window(question)
    marks = _Marks()
    executor = VoiceExecutor()
    runtime = await build_chat_runtime(
        RuntimeOptions(config_path=config, agents_dir=agents_dir),
        gate_factory=lambda settings, front: _DenyGate(),
    )
    pipeline = SpeechPipeline(
        tts_loader,
        executor,
        registry.tts_voice,
        _FirstAudioSink(marks),
        runtime,
        segmenter=SentenceSegmenter(first_clause=True),
    )
    channel = _SpeakingChannel(pipeline, marks)
    turns: list[asyncio.Task] = []
    try:
        session = await runtime.open_session(
            runtime.memory.conversations.start_conversation("bench"), channel
        )
        await session.handle(f"/t {WARMUP_PROMPT}")
        channel.finishing = None

        async def on_final(transcript: Transcript, interrupting: bool) -> None:
            turns.append(asyncio.ensure_future(session.handle(f"/v {transcript.text}", "audio")))

        async def on_error(code: str, detail: str) -> None:
            return None

        audio = AudioSession(
            registry.get_vad(),
            lambda: _TimedStt(registry.get_stt(registry.stt_alias), marks),
            executor,
            runtime.front.persona.language,
            on_final,
            on_error,
            runtime,
            end_silence_ms=runtime.settings.voice.end_silence_ms,
        )
        audio.open()
        started = time.perf_counter()
        for index in range(len(microphone) // WINDOW_BYTES):
            audio.feed(microphone[index * WINDOW_BYTES : (index + 1) * WINDOW_BYTES])
            if index == last_speech:
                marks.end_of_speech = time.perf_counter()
            await asyncio.sleep(
                max(0.0, started + (index + 1) * WINDOW_MS / 1_000 - time.perf_counter())
            )
        await asyncio.wait_for(marks.audio.wait(), FIRST_AUDIO_TIMEOUT_S)
        await asyncio.gather(*turns, return_exceptions=True)
        if channel.finishing is not None:
            await asyncio.gather(channel.finishing, return_exceptions=True)
        await audio.aclose()
        return marks.sample()
    except TimeoutError:
        return None
    finally:
        await pipeline.cancel()
        executor.close()
        await runtime.aclose()


class _DenyGate:
    async def confirm(self, request: object) -> bool:
        return False
