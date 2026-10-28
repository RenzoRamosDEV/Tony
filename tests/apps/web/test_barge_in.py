"""Barge-in over /ws/chat: speaking over Tony cancels his audio (specs/voice-input)."""

from __future__ import annotations

import json
import threading
import time
from array import array
from pathlib import Path
from typing import Any

from tests.apps.web.helpers import (
    FakeVoice,
    build_test_app,
    delegating,
    drain_mixed,
    open_chat,
    send,
)
from tests.fakes.conversation import BLOCK_UNTIL_INTERRUPT
from tests.fakes.voice import FULL_SCALE_RMS, FakeStt, FakeTts, FakeVad
from tony.core.voice.ports import VAD_WINDOW_SAMPLES

AUDIO_START = {"sample_rate": 16000, "channels": 1, "format": "f32"}
LONG = {
    "display_text": "Son las diez y media, señor. Tiene una reunión a las once.",
    "speech_text": "Son las diez y media, señor. Tiene una reunión a las once.",
}
WINDOW_MS = 32


class GatedTts(FakeTts):
    """Synthesizes the first piece, then holds every other one until released."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def synthesize(self, text: str, voice: str):
        if self.sentences:
            self.gate.wait(timeout=5)
        return super().synthesize(text, voice)


def windows(probability: float, count: int) -> list[bytes]:
    window = array("f", [probability * FULL_SCALE_RMS] * VAD_WINDOW_SAMPLES).tobytes()
    return [window] * count


def speak_over(ws: Any, speech_windows: int = 12, silence_windows: int = 16) -> None:
    for frame in windows(0.9, speech_windows) + windows(0.0, silence_windows):
        ws.send_bytes(frame)


def types(seen: list[Any]) -> list[str]:
    return [m["type"] if isinstance(m, dict) else "bin" for m in seen]


def records(tmp_path: Path) -> list[dict[str, Any]]:
    logs = [p for p in (tmp_path / "logs").rglob("chat-*.jsonl")]
    return [json.loads(line) for p in logs for line in p.read_text("utf-8").splitlines()]


def wait_for_record(tmp_path: Path, type_: str, timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = [r for r in records(tmp_path) if r["type"] == type_]
        if found:
            return found[-1]
        time.sleep(0.01)
    raise AssertionError(f"no se registró {type_}")


def gated_voice(text: str) -> tuple[FakeVoice, GatedTts]:
    tts = GatedTts()
    return FakeVoice(FakeVad(), FakeStt(text), tts), tts


def start_listening(ws: Any) -> None:
    send(ws, "audio.start", AUDIO_START)


def test_speaking_over_tony_cancels_his_audio_then_transcribes(tmp_path: Path) -> None:
    engines, tts = gated_voice("para, ¿qué tiempo hace?")
    try:
        with build_test_app(tmp_path, turns=[LONG, "Hace sol."], voice=engines) as client:
            with open_chat(client) as (ws, _):
                start_listening(ws)
                send(ws, "user.text", {"text": "/v hora"})
                before = drain_mixed(ws, "bin")
                speak_over(ws)
                after = drain_mixed(ws, "assistant.final")
    finally:
        tts.gate.set()

    speaking = next(m for m in before if isinstance(m, dict) and m["type"] == "tts.start")
    order = types(after)
    assert order.index("tts.cancelled") < order.index("stt.final") < order.index("user.accepted")
    cancelled = after[order.index("tts.cancelled")]
    assert cancelled["payload"] == {"message_id": speaking["message_id"]}
    assert after[-1]["payload"]["display_text"] == "Hace sol."
    barge_in = wait_for_record(tmp_path, "barge_in")
    assert barge_in["payload"] == {
        "message_id": speaking["message_id"],
        "speech_ms": 9 * WINDOW_MS,
    }


def test_a_turn_still_generating_is_closed_with_what_it_said(tmp_path: Path) -> None:
    generating = {
        "display_text": "",
        "chunks": ["Son las"],
        "speech_chunks": ["Son las diez y media, señor. Tiene una reunión."],
        BLOCK_UNTIL_INTERRUPT: True,
    }
    engines, tts = gated_voice("para, ¿qué tiempo hace?")
    try:
        with build_test_app(tmp_path, turns=[generating, "Hace sol."], voice=engines) as client:
            with open_chat(client) as (ws, _):
                start_listening(ws)
                send(ws, "user.text", {"text": "/v hora"})
                drain_mixed(ws, "bin")
                speak_over(ws)
                seen = drain_mixed(ws, "assistant.final")
                seen += drain_mixed(ws, "assistant.final")
    finally:
        tts.gate.set()

    order = types(seen)
    finals = [m for m in seen if isinstance(m, dict) and m["type"] == "assistant.final"]
    assert [f["payload"]["display_text"] for f in finals] == ["Son las …", "Hace sol."]
    assert finals[0]["payload"]["speech_text"] is None
    assert "error" not in order
    assert order.index("tts.cancelled") < order.index("assistant.final")
    assert order.index("assistant.final") < order.index("user.accepted")


def test_with_a_delegated_task_only_the_audio_stops(tmp_path: Path) -> None:
    engines = FakeVoice(FakeVad(), FakeStt("¿cómo va?"), FakeTts())
    scripts = {"larga": [("sleep", 100)]}
    with build_test_app(
        tmp_path, turns=[LONG, delegating("larga")], scripts=scripts, voice=engines
    ) as client:
        with open_chat(client) as (ws, _):
            start_listening(ws)
            send(ws, "user.text", {"text": "/v hora"})
            spoken = drain_mixed(ws, "tts.end")
            send(ws, "user.text", {"text": "/t tarea larga"})
            drain_mixed(ws, "task.running")
            speak_over(ws)
            seen = drain_mixed(ws, "error")
            if "stt.final" not in types(seen):
                seen += drain_mixed(ws, "stt.final")
            tasks = list(client.app.state.hub.runtime.orchestrator.tasks.values())
            statuses = [task.status.value for task in tasks]
            interrupts = client.app.state.runner.interrupts

    message_id = next(m for m in spoken if isinstance(m, dict) and m["type"] == "tts.end")[
        "message_id"
    ]
    order = types(seen)
    assert seen[order.index("tts.cancelled")]["payload"] == {"message_id": message_id}
    assert order.index("tts.cancelled") < order.index("stt.final")
    assert seen[order.index("error")]["payload"]["code"] == "turn_in_progress"
    assert statuses == ["running"]
    assert interrupts == 0


def test_tony_hearing_himself_is_discarded_as_echo(tmp_path: Path) -> None:
    engines, tts = gated_voice("las diez y media")
    try:
        with build_test_app(tmp_path, turns=[LONG], voice=engines) as client:
            with open_chat(client) as (ws, _):
                start_listening(ws)
                send(ws, "user.text", {"text": "/v hora"})
                drain_mixed(ws, "bin")
                speak_over(ws)
                echo = wait_for_record(tmp_path, "barge_in.echo")
                send(ws, "user.text", {"text": " "})
                seen = drain_mixed(ws, "error")
    finally:
        tts.gate.set()

    assert "tts.cancelled" in types(seen)
    assert "stt.final" not in types(seen) and "user.accepted" not in types(seen)
    assert seen[-1]["payload"]["code"] == "empty_text"
    assert echo["payload"] == {"chars": len("las diez y media")}


def test_a_short_transcript_inside_the_reply_is_not_echo(tmp_path: Path) -> None:
    engines, tts = gated_voice("las diez")
    try:
        with build_test_app(tmp_path, turns=[LONG, "Sí."], voice=engines) as client:
            with open_chat(client) as (ws, _):
                start_listening(ws)
                send(ws, "user.text", {"text": "/v hora"})
                drain_mixed(ws, "bin")
                speak_over(ws)
                seen = drain_mixed(ws, "assistant.final")
    finally:
        tts.gate.set()

    assert {"stt.final", "user.accepted"} <= set(types(seen))


def test_playback_stopped_is_accepted_silently_for_any_message(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=FakeVoice(FakeVad(), FakeStt("x"), FakeTts())) as client:
        with open_chat(client) as (ws, _):
            send(ws, "playback.stopped", {"message_id": "m-desconocido"})
            send(ws, "playback.stopped", {})
            bad = ws.receive_json()
            send(ws, "user.text", {"text": ""})
            marker = ws.receive_json()

    assert bad["payload"]["code"] == "bad_payload"
    assert marker["payload"]["code"] == "empty_text"


def test_after_playback_stopped_moderate_speech_is_heard_again(tmp_path: Path) -> None:
    engines = FakeVoice(FakeVad(), FakeStt("¿y mañana?"), FakeTts())
    with build_test_app(tmp_path, turns=[LONG, "Lloverá."], voice=engines) as client:
        with open_chat(client) as (ws, _):
            start_listening(ws)
            send(ws, "user.text", {"text": "/v hora"})
            ended = drain_mixed(ws, "tts.end")[-1]
            send(ws, "playback.stopped", {"message_id": ended["message_id"]})
            for frame in windows(0.6, 12) + windows(0.0, 16):
                ws.send_bytes(frame)
            seen = drain_mixed(ws, "assistant.final")

    assert "tts.cancelled" not in types(seen)
    assert seen[0]["type"] == "stt.final" and seen[-1]["payload"]["display_text"] == "Lloverá."
