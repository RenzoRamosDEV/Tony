"""Audio input over /ws/chat (specs/voice-input, ws-chat-protocol, web-server)."""

from __future__ import annotations

import json
from array import array
from pathlib import Path
from typing import Any

from tests.apps.web.helpers import (
    FRAME_BYTES,
    FakeVoice,
    advance,
    build_test_app,
    delegating,
    drain_mixed,
    drain_until,
    frames_of,
    hello,
    open_chat,
    send,
    settle,
    wait_detached,
)
from tests.fakes.voice import FakeStt, FakeTts, FakeVad
from tests.fixtures.audio.generate import tone

AUDIO_START = {"sample_rate": 16000, "channels": 1, "format": "f32"}
ANSWER = {"display_text": "Son las diez y media.", "speech_text": "Son las diez y media."}


def voice(text: str = "¿qué hora es?") -> FakeVoice:
    return FakeVoice(FakeVad(), FakeStt(text), FakeTts())


def speak_one_second(ws: Any) -> None:
    pcm = array("f", tone(1_000)).tobytes()
    for start in range(0, len(pcm), FRAME_BYTES):
        ws.send_bytes(pcm[start : start + FRAME_BYTES])


def types(seen: list[Any]) -> list[str]:
    return [m["type"] if isinstance(m, dict) else "bin" for m in seen]


def test_binary_before_hello_is_rejected_and_the_socket_stays_usable(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=voice()) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_bytes(b"\0" * 64)
            error = ws.receive_json()
            ok = hello(ws)

    assert error["type"] == "error" and error["payload"]["code"] == "hello_required"
    assert error["seq"] == 0 and ok["type"] == "hello.ok"


def test_audio_start_is_accepted_only_with_the_supported_format(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", {"sample_rate": 44100, "channels": 2, "format": "f32"})
            unsupported = ws.receive_json()
            send(ws, "audio.start", AUDIO_START)
            send(ws, "audio.start", AUDIO_START)
            busy = ws.receive_json()
            settle(client)
            assert client.app.state.hub.audio is not None

    assert unsupported["payload"]["code"] == "unsupported_audio"
    assert busy["payload"]["code"] == "audio_in_progress"


def test_without_the_voice_extra_audio_start_is_unavailable(tmp_path: Path) -> None:
    with build_test_app(tmp_path) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", AUDIO_START)
            error = ws.receive_json()
            ws.send_bytes(b"\0" * 2560)
            after = ws.receive_json()

    assert error["payload"]["code"] == "voice_unavailable"
    assert "uv sync --extra voice" in error["payload"]["detail"]
    assert after["payload"]["code"] == "audio_not_started"


def test_frames_outside_an_utterance_are_rejected_without_closing(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=voice()) as client:
        with open_chat(client) as (ws, _):
            ws.send_bytes(b"\0" * 2560)
            before = ws.receive_json()
            send(ws, "audio.end", {})
            never_opened = ws.receive_json()
            send(ws, "audio.start", AUDIO_START)
            send(ws, "audio.end", {})
            ws.send_bytes(b"\0" * 2560)
            after = ws.receive_json()
            send(ws, "set_mode", {"reply_mode": "text"})
            settle(client)

    assert before["payload"]["code"] == "audio_not_started"
    assert never_opened["payload"]["code"] == "audio_not_started"
    assert after["payload"]["code"] == "audio_not_started"


def test_frame_size_limit_is_16_kib(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", AUDIO_START)
            ws.send_bytes(b"\0" * 20_000)
            too_large = ws.receive_json()
            ws.send_bytes(b"\0" * 2560)
            ws.send_bytes(b"\0" * 16_384)
            send(ws, "audio.end", {})
            send(ws, "set_mode", {"reply_mode": "text"})
            settle(client)
            send(ws, "set_mode", {"reply_mode": "loud"})
            still_open = ws.receive_json()

    assert too_large["payload"]["code"] == "audio_frame_too_large"
    assert still_open["payload"]["code"] == "reply_mode_locked"


def test_speech_then_silence_is_transcribed_and_answered_by_voice(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", AUDIO_START)
            for frame in frames_of("speech_1500ms.wav"):
                ws.send_bytes(frame)
            seen = drain_mixed(ws, "tts.end")
            send(ws, "audio.end", {})
            settle(client)

    order = types(seen)
    assert order[:2] == ["stt.final", "user.accepted"]
    assert order.index("tts.start") < order.index("tts.chunk.meta") < order.index("bin")
    assert order.index("assistant.final") < order.index("tts.end")
    final, accepted = seen[0], seen[1]
    assert final["payload"]["text"] == "¿qué hora es?"
    assert accepted["payload"] == {
        "message_id": final["payload"]["message_id"],
        "effective_mode": "voice",
        "client_id": None,
    }
    assert accepted["message_id"] == final["message_id"] == final["payload"]["message_id"]
    first_meta = next(m for m in seen if isinstance(m, dict) and m["type"] == "tts.chunk.meta")
    assert first_meta["payload"] == {"seq": 0, "sentence_index": 0}
    assert isinstance(seen[order.index("bin")], bytes) and len(seen[order.index("bin")]) > 0
    assistant_final = next(
        m for m in seen if isinstance(m, dict) and m["type"] == "assistant.final"
    )
    assert assistant_final["payload"]["speech_text"] == "Son las diez y media."
    assert first_meta["message_id"] == assistant_final["message_id"]


def test_audio_end_transcribes_the_pending_speech(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            send(ws, "audio.end", {})
            seen = drain_until(ws, "stt.final")
            send(ws, "audio.start", AUDIO_START)
            drain_until(ws, "assistant.final")

    assert types(seen) == ["stt.final"]


def test_empty_transcription_starts_no_turn(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice("")) as client:
        with open_chat(client) as (ws, _):
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            send(ws, "audio.end", {})
            settle(client)
            send(ws, "set_mode", {"reply_mode": "loud"})
            only = ws.receive_json()
        assert client.app.state.runner.prompts == []

    assert only["payload"]["code"] == "reply_mode_locked"


def test_a_spoken_prefix_applies_like_a_typed_one(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice("/t qué hora es")) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            send(ws, "audio.end", {})
            seen = drain_until(ws, "assistant.final")
        messages = client.get(f"/api/conversations/{conversation}/messages").json()

    accepted = next(m for m in seen if m["type"] == "user.accepted")
    assert accepted["payload"]["effective_mode"] == "text"
    assert "tts.start" not in types(seen)
    assert messages[0]["content"] == "qué hora es"


def test_transcription_during_a_turn_is_rejected(tmp_path: Path) -> None:
    scripts = {"lenta": [("sleep", 10)]}
    with build_test_app(
        tmp_path, turns=[delegating("lenta"), ANSWER], scripts=scripts, voice=voice()
    ) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "tarea"})
            drain_until(ws, "task.running")
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            send(ws, "audio.end", {})
            seen = drain_until(ws, "error")
            if "stt.final" not in types(seen):
                seen += drain_until(ws, "stt.final")
            settle(client)
            assert len(client.app.state.runner.prompts) == 1
            advance(client, 10)
            drain_until(ws, "assistant.final")

    assert {"stt.final", "error"} <= set(types(seen))
    rejected = next(m for m in seen if m["type"] == "error")
    assert rejected["payload"]["code"] == "turn_in_progress" and rejected["seq"] == 0


def test_closing_the_socket_discards_the_open_utterance(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice()) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            settle(client)
        wait_detached(client)
        assert client.app.state.hub.audio is None
        with client.websocket_connect("/ws/chat") as ws2:
            ok = hello(ws2, conversation)
            send(ws2, "set_mode", {"reply_mode": "loud"})
            only = ws2.receive_json()

    assert ok["payload"]["last_seq"] == 0
    assert only["payload"]["code"] == "reply_mode_locked"
    assert client.app.state.runner.prompts == []


def test_only_the_transcription_is_persisted_and_logged_without_its_text(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[ANSWER], voice=voice()) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "audio.start", AUDIO_START)
            speak_one_second(ws)
            send(ws, "audio.end", {})
            drain_mixed(ws, "tts.end")
            settle(client)
        messages = client.get(f"/api/conversations/{conversation}/messages").json()

    assert messages[0]["content"] == "¿qué hora es?"
    logs = [p for p in (tmp_path / "logs").rglob("*") if p.is_file()]
    assert [p.name for p in logs] == [f"chat-{conversation}.jsonl"]
    records = [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]
    final = next(r for r in records if r["type"] == "stt.final")
    assert final["payload"] == {"chars": 13, "duration_ms": final["payload"]["duration_ms"]}
    assert 900 <= final["payload"]["duration_ms"] <= 1_100
    assert "text" not in final["payload"]
    memory = [p.name for p in (tmp_path / "memory").iterdir()]
    assert not any(name.endswith((".wav", ".pcm", ".raw")) for name in memory)
    assert not list(tmp_path.rglob("*.wav"))


# --- listening while Tony speaks: AudioSession with a fake playback window (specs/voice-input) ---

import asyncio  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

from tests.fakes.sinks import ListEventSink  # noqa: E402
from tests.fakes.voice import FULL_SCALE_RMS  # noqa: E402
from tony.apps.web.audio_ws import AudioSession  # noqa: E402
from tony.core.voice.executor import VoiceExecutor  # noqa: E402
from tony.core.voice.ports import VAD_WINDOW_SAMPLES  # noqa: E402

WINDOW_MS = 32


def windows(probability: float, count: int) -> list[bytes]:
    window = array("f", [probability * FULL_SCALE_RMS] * VAD_WINDOW_SAMPLES).tobytes()
    return [window] * count


class FakePlayback:
    def __init__(self, speaking: bool = True) -> None:
        self.playing = speaking

    def speaking(self) -> bool:
        return self.playing


class CountingVad(FakeVad):
    def __init__(self) -> None:
        super().__init__()
        self.thresholds: list[float] = []

    def classify(self, window: bytes, threshold: float) -> bool:
        self.thresholds.append(threshold)
        return super().classify(window, threshold)


class Listener:
    def __init__(self) -> None:
        self.finals: list[tuple[str, bool]] = []
        self.barge_ins: list[int] = []
        self.errors: list[str] = []

    async def on_final(self, transcript, interrupting: bool) -> None:
        self.finals.append((transcript.text, interrupting))

    async def on_error(self, code: str, detail: str) -> None:
        self.errors.append(code)

    async def on_barge_in(self, speech_ms: int) -> None:
        self.barge_ins.append(speech_ms)


@pytest.fixture
def executor():
    executor = VoiceExecutor()
    yield executor
    executor.close()


def listening(executor, playback: FakePlayback, vad=None, barge_in: bool = True):
    listener = Listener()
    session = AudioSession(
        vad or FakeVad(),
        lambda: FakeStt("para, ¿qué tiempo hace?"),
        executor,
        "es",
        listener.on_final,
        listener.on_error,
        ListEventSink(),
        end_silence_ms=500,
        barge_in=barge_in,
        barge_in_threshold=0.8,
        barge_in_min_speech_ms=280,
        speaking=playback.speaking,
        on_barge_in=listener.on_barge_in,
    )
    return session, listener


async def feed_all(session: AudioSession, items: list[bytes]) -> None:
    for item in items:
        assert session.feed(item)
    await settled(session)


async def settled(session: AudioSession, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while session.busy:
        assert time.monotonic() < deadline, "the session did not settle"
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)


async def test_a_moderate_voice_while_tony_speaks_is_silence(executor) -> None:
    session, listener = listening(executor, FakePlayback())
    session.open()
    try:
        await feed_all(session, windows(0.6, 32) + windows(0.0, 20))
    finally:
        await session.aclose()

    assert listener.barge_ins == [] and listener.finals == []


async def test_280ms_of_strict_speech_barges_in_once_and_the_utterance_goes_on(executor) -> None:
    session, listener = listening(executor, FakePlayback())
    session.open()
    try:
        await feed_all(session, windows(0.9, 8))
        assert listener.barge_ins == []
        await feed_all(session, windows(0.9, 1))
        assert listener.barge_ins == [9 * WINDOW_MS]
        await feed_all(session, windows(0.9, 10) + windows(0.0, 15))
        assert listener.finals == []
        await feed_all(session, windows(0.0, 1))
    finally:
        await session.aclose()

    assert listener.barge_ins == [9 * WINDOW_MS]
    assert listener.finals == [("para, ¿qué tiempo hace?", True)]


async def test_250ms_of_speech_does_not_barge_in(executor) -> None:
    session, listener = listening(executor, FakePlayback())
    session.open()
    try:
        await feed_all(session, windows(0.9, 8) + windows(0.0, 20))
    finally:
        await session.aclose()

    assert listener.barge_ins == [] and listener.finals == []


async def test_after_playback_the_normal_threshold_applies_again(executor) -> None:
    playback = FakePlayback()
    vad = CountingVad()
    session, listener = listening(executor, playback, vad)
    session.open()
    try:
        await feed_all(session, windows(0.6, 2))
        playback.playing = False
        await feed_all(session, windows(0.6, 12) + windows(0.0, 16))
    finally:
        await session.aclose()

    assert vad.thresholds[:2] == [0.8, 0.8] and set(vad.thresholds[2:]) == {0.5}
    assert listener.barge_ins == []
    assert listener.finals == [("para, ¿qué tiempo hace?", False)]


async def test_with_barge_in_disabled_frames_during_playback_are_dropped(executor) -> None:
    vad = CountingVad()
    session, listener = listening(executor, FakePlayback(), vad, barge_in=False)
    session.open()
    try:
        await feed_all(session, windows(0.9, 32) + windows(0.0, 20))
    finally:
        await session.aclose()

    assert vad.thresholds == []
    assert listener.barge_ins == [] and listener.finals == [] and listener.errors == []


async def test_a_session_without_playback_hears_moderate_speech(executor) -> None:
    listener = Listener()
    session = AudioSession(
        FakeVad(),
        lambda: FakeStt("hola"),
        executor,
        "es",
        listener.on_final,
        listener.on_error,
        ListEventSink(),
    )
    session.open()
    try:
        await feed_all(session, windows(0.6, 12) + windows(0.0, 16))
    finally:
        await session.aclose()

    assert listener.finals == [("hola", False)]


async def test_the_configured_end_silence_closes_the_utterance(executor) -> None:
    listener = Listener()
    session = AudioSession(
        FakeVad(),
        lambda: FakeStt("hola"),
        executor,
        "es",
        listener.on_final,
        listener.on_error,
        ListEventSink(),
        end_silence_ms=700,
    )
    session.open()
    try:
        await feed_all(session, windows(0.9, 12) + windows(0.0, 19))
        assert listener.finals == []
        await feed_all(session, windows(0.0, 3))
    finally:
        await session.aclose()

    assert listener.finals == [("hola", False)]


async def test_a_discarded_burst_rearms_the_barge_in(executor) -> None:
    session, listener = listening(executor, FakePlayback())
    session.open()
    try:
        await feed_all(session, windows(0.9, 9) + windows(0.0, 16))
        await feed_all(session, windows(0.9, 12) + windows(0.0, 16))
    finally:
        await session.aclose()

    assert listener.barge_ins == [9 * WINDOW_MS, 9 * WINDOW_MS]
    assert listener.finals == [("para, ¿qué tiempo hace?", True)]


@pytest.mark.parametrize(("minimum", "fired"), [(9 * WINDOW_MS, True), (9 * WINDOW_MS + 1, False)])
async def test_the_minimum_speech_is_inclusive(executor, minimum: int, fired: bool) -> None:
    listener = Listener()
    session = AudioSession(
        FakeVad(),
        lambda: FakeStt("x"),
        executor,
        "es",
        listener.on_final,
        listener.on_error,
        ListEventSink(),
        barge_in_min_speech_ms=minimum,
        speaking=FakePlayback().speaking,
        on_barge_in=listener.on_barge_in,
    )
    session.open()
    try:
        await feed_all(session, windows(0.9, 9) + windows(0.0, 16))
    finally:
        await session.aclose()

    assert bool(listener.barge_ins) is fired
