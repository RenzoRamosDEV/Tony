import asyncio
import threading

from tests.fakes.voice import (
    RecordingAudioOutput,
    ScriptedAudioInput,
    ScriptedStt,
    TextTts,
    ThresholdVad,
)
from tony.core.config.settings import VoiceSettings
from tony.core.events import core_events as ev
from tony.core.voice.ports import Engines, Unavailable
from tony.core.voice.service import VoiceCast, VoiceService

ALEX = "kokoro/em_alex"
DORA = "kokoro/ef_dora"
EDITH = "kokoro/ef_dora,bf_emma"
CAST = VoiceCast(front="jarvis", front_voice=ALEX, worker_voice=DORA, guard_voice=EDITH)
VOICE_THREADS = {"tony-vad", "tony-stt", "tony-tts", "tony-playback", "tony-voice-load"}


class FakeLoader:
    def __init__(self, result=None, *, gate: threading.Event | None = None) -> None:
        self.audio = ScriptedAudioInput()
        self.output = RecordingAudioOutput()
        self.stt = ScriptedStt()
        self.tts = TextTts()
        self.vad = ThresholdVad()
        self._result = result
        self._gate = gate
        self.calls: list[tuple[VoiceSettings, tuple[str, ...]]] = []

    def engines(self) -> Engines:
        return Engines(self.audio, self.output, self.vad, self.stt, self.tts)

    def __call__(self, settings, voices):
        self.calls.append((settings, voices))
        if self._gate is not None:
            self._gate.wait(5)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result if isinstance(self._result, Unavailable) else self.engines()


class Harness:
    def __init__(self, loader: FakeLoader, **options) -> None:
        self.loader = loader
        self.published: list[dict] = []
        self.commands: list[dict] = []
        self.service = VoiceService(loader, **options)

    def start(self, settings: VoiceSettings | None = None, cast: VoiceCast = CAST) -> None:
        loop = asyncio.get_running_loop()
        self.service.start(
            settings or VoiceSettings(),
            cast,
            publish=self.published.append,
            submit=self.commands.append,
            post=loop.call_soon_threadsafe,
        )

    def observe(self, *events) -> None:
        for event in events:
            self.service.observe(event)

    def states(self) -> list[tuple[str, str | None]]:
        return [(e["state"], e["reason"]) for e in self.published if e["type"] == "voice_state"]

    def of_type(self, kind: str) -> list[dict]:
        return [e for e in self.published if e["type"] == kind]

    async def until(self, predicate, timeout: float = 5) -> None:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.005)

    async def ready(self) -> None:
        await self.until(lambda: ("ready", None) in self.states())

    def speaking_turn(self, speaks: bool = True) -> None:
        self.observe(ev.turn_started("jarvis", "voice", "auto", speaks=speaks, writes=not speaks))


def voice_threads() -> set[str]:
    return {t.name for t in threading.enumerate()} & VOICE_THREADS
