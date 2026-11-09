"""Latency benchmark (uv run pytest -m voice tests/voice/test_latency.py -s).

Voice leg: end of the utterance -> first played audio of a reply without tools, with the real
VAD, STT and TTS, playback to a null output and a fake chat engine (the real one with
TONY_EVALS=1). Text leg (TONY_EVALS=1 only): typed message -> first token. Reports p50 and
the cold/warm stage report with event-loop lag; never asserts the 1 s / 2 s targets.
"""

import asyncio
import os
import statistics
import threading
import time
from dataclasses import replace

import pytest

pytestmark = pytest.mark.voice

pytest.importorskip("kokoro")

from tests.core.orchestrator.test_runtime import Harness, home_for  # noqa: E402
from tests.core.orchestrator.tony_home import set_config  # noqa: E402
from tests.fakes.fake_chat import FakeChatEngine, Say  # noqa: E402
from tests.fakes.voice import ScriptedAudioInput  # noqa: E402
from tests.voice.test_engines import to_input_rate  # noqa: E402
from tony.core.voice.engines.loader import build_engines  # noqa: E402
from tony.core.voice.ports import WINDOW_BYTES, Clip  # noqa: E402
from tony.core.voice.service import VoiceService  # noqa: E402
from tony.core.voice.timing import (  # noqa: E402
    LoopLagSampler,
    StageTimings,
    format_report,
    summarise,
)

RUNS = 20
REAL_MODEL = os.environ.get("TONY_EVALS") == "1"
REPLY = ("Son las cinco y media, señor.", " ¿Desea algo más?")


class TimedInput(ScriptedAudioInput):
    def __init__(self, frames) -> None:
        super().__init__(frames)
        self.closed_at: list[float] = []

    def close(self) -> None:
        self.closed_at.append(time.perf_counter())
        super().close()


class NullOutput:
    def __init__(self) -> None:
        self.first_played: list[float] = []
        self.played = threading.Event()

    def play(self, clip: Clip) -> None:
        self.first_played.append(time.perf_counter())
        self.played.set()

    def stop(self) -> None:
        return None


@pytest.fixture(autouse=True)
def home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))


def chat_engine():
    if REAL_MODEL:
        from tony.core.orchestrator.claude_engine import ClaudeEngine

        return ClaudeEngine()
    return FakeChatEngine(*([Say(*REPLY)] for _ in range(RUNS)))


def utterance_frames(engines) -> list[bytes]:
    pcm = to_input_rate(engines.tts.synthesize("¿Qué hora es?", "kokoro/em_alex"))
    pcm += bytes(WINDOW_BYTES * 30)
    return [pcm[i : i + WINDOW_BYTES] for i in range(0, len(pcm), WINDOW_BYTES)]


@pytest.mark.timeout(300)
async def test_latency_p50(tmp_path, record_property):
    home, _ = home_for(tmp_path)
    set_config(home, "reply_mode: auto\n")
    output = NullOutput()
    inputs: list[TimedInput] = []

    def loader(settings, voices):
        engines = build_engines(settings, voices)
        inputs.append(TimedInput(utterance_frames(engines)))
        return replace(engines, audio_input=inputs[0], audio_output=output)

    timings = StageTimings()
    lag = LoopLagSampler()
    voice = VoiceService(loader, timings=timings)
    voice_s: list[float] = []
    text_s: list[float] = []
    async with Harness(home, chat_engine(), voice=voice) as harness:
        lag.start()
        await harness.until(lambda: voice.ready, timeout=120)
        for run in range(RUNS):
            output.played.clear()
            mark = len(output.first_played)
            harness.send(type="listen")
            await harness.until(output.played.is_set, timeout=60)
            voice_s.append(output.first_played[mark] - inputs[0].closed_at[run])
            await harness.until(lambda r=run: len(_turn_results(harness)) == r + 1, timeout=60)
            assert voice.wait_silent(30)
        if REAL_MODEL:
            for _ in range(RUNS):
                tokens = len(harness.of("token"))
                started = time.perf_counter()
                harness.send(type="send_message", text="/t Hola")
                await harness.until(lambda t=tokens: len(harness.of("token")) > t, timeout=60)
                text_s.append(time.perf_counter() - started)
                await asyncio.sleep(0)

    await lag.stop()
    voice_p50 = statistics.median(voice_s)
    record_property("voice_first_audio_p50_s", round(voice_p50, 3))
    print(f"\nvoice first audio p50: {voice_p50:.3f} s over {voice_s}")
    print(format_report(summarise(timings), lag))
    if text_s:
        text_p50 = statistics.median(text_s)
        record_property("text_first_token_p50_s", round(text_p50, 3))
        print(f"text first token p50: {text_p50:.3f} s over {text_s}")
    else:
        print("text first token p50: not measured (set TONY_EVALS=1)")


def _turn_results(harness):
    return [e for e in harness.of("result") if e.get("scope") == "turn"]
