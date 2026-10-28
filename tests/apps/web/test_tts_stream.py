"""Spoken replies over /ws/chat: tts.* framing, cancellation, degradation (specs/voice-output)."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.apps.web.helpers import (
    FakeVoice,
    build_test_app,
    drain_mixed,
    drain_until,
    hello,
    open_chat,
    send,
    settle,
    wait_detached,
)
from tests.fakes.voice import FakeStt, FakeTts, FakeVad
from tony.core.voice.cleanup import SCREEN_SUFFIX
from tony.core.voice.ports import AudioChunk, Tts

TWO = {
    "display_text": "Son las diez. Tiene una reunión.",
    "speech_text": "Son las diez. Tiene una reunión.",
}
AUDIO_START = {"sample_rate": 16000, "channels": 1, "format": "f32"}


class GatedTts(FakeTts):
    """Synthesizes the first sentence at once and blocks the next until `release()`."""

    def __init__(self, fail_at_sentence: int | None = None) -> None:
        super().__init__(fail_at_sentence)
        self.gate = threading.Event()

    def synthesize(self, text: str, voice: str) -> Iterator[AudioChunk]:
        if self.sentences:
            self.gate.wait(timeout=5)
        return super().synthesize(text, voice)

    def release(self) -> None:
        self.gate.set()


def voice(tts: Tts | None = None, loader=None) -> FakeVoice:
    return FakeVoice(FakeVad(), FakeStt("hola"), tts or FakeTts(), tts_factory=loader)


def types(seen: list[Any]) -> list[str]:
    return [m["type"] if isinstance(m, dict) else "bin" for m in seen]


def envelopes(seen: list[Any], type_: str) -> list[dict[str, Any]]:
    return [m for m in seen if isinstance(m, dict) and m["type"] == type_]


def test_voice_reply_streams_meta_then_binary_per_chunk_with_the_final_message_id(
    tmp_path: Path,
) -> None:
    with build_test_app(tmp_path, turns=[TWO], voice=voice()) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "tts.end")

    order = types(seen)
    assert order == [
        "user.accepted",
        "usage",
        "assistant.final",
        "tts.start",
        "tts.chunk.meta",
        "bin",
        "tts.chunk.meta",
        "bin",
        "tts.chunk.meta",
        "bin",
        "tts.chunk.meta",
        "bin",
        "tts.end",
    ]
    final = envelopes(seen, "assistant.final")[0]
    metas = envelopes(seen, "tts.chunk.meta")
    assert [m["payload"] for m in metas] == [
        {"seq": 0, "sentence_index": 0},
        {"seq": 1, "sentence_index": 0},
        {"seq": 2, "sentence_index": 1},
        {"seq": 3, "sentence_index": 1},
    ]
    assert metas[0] == {
        "v": 1,
        "type": "tts.chunk.meta",
        "seq": metas[0]["seq"],
        "conversation_id": conversation,
        "message_id": final["message_id"],
        "payload": {"seq": 0, "sentence_index": 0},
    }
    assert {m["message_id"] for m in envelopes(seen, "tts.start") + envelopes(seen, "tts.end")} == {
        final["message_id"]
    }
    assert envelopes(seen, "tts.start")[0]["payload"] == {"message_id": final["message_id"]}
    assert [m["seq"] for m in seen if isinstance(m, dict)] == list(range(1, 10))
    sentence_pause = 24_000 * 160 // 1_000 * 2
    assert [len(frame) for frame in seen if isinstance(frame, bytes)] == [
        7_200,
        7_200 + sentence_pause,
        7_200,
        7_200,
    ]


def test_text_mode_sends_no_tts(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[TWO], voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/t hora"})
            seen = drain_until(ws, "assistant.final")
            send(ws, "set_mode", {"reply_mode": "loud"})
            after = ws.receive_json()

    assert "tts.start" not in types(seen) and after["payload"]["code"] == "invalid_reply_mode"


def test_both_mode_shows_everything_and_speaks_only_the_speech_text(tmp_path: Path) -> None:
    tts = FakeTts()
    turn = {"display_text": "| a | b |\n|---|---|\n| 1 | 2 |", "speech_text": "Dos filas."}
    with build_test_app(tmp_path, turns=[turn], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/b tabla"})
            seen = drain_mixed(ws, "tts.end")

    final = envelopes(seen, "assistant.final")[0]["payload"]
    assert final["display_text"].startswith("| a | b |") and final["speech_text"] == "Dos filas."
    assert tts.sentences == ["Dos filas."]


def test_without_speech_text_the_cleaned_display_text_is_spoken(tmp_path: Path) -> None:
    tts = FakeTts()
    turn = {"display_text": "Aquí tiene la tabla:\n|a|b|\n|1|2|", "speech_text": None}
    with build_test_app(tmp_path, turns=[turn], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v tabla"})
            drain_mixed(ws, "tts.end")

    assert tts.sentences == ["Aquí tiene la tabla:", SCREEN_SUFFIX]


def test_a_front_that_streams_speech_fragments_speaks_before_the_final(tmp_path: Path) -> None:
    turn = {**TWO, "speech_chunks": ["Son las diez. ", "Tiene una reunión."]}
    with build_test_app(tmp_path, turns=[turn], voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "tts.end")

    order = types(seen)
    assert order.index("tts.chunk.meta") < order.index("assistant.final")
    assert order.count("tts.chunk.meta") == 4 and order.count("bin") == 4
    assert order.index("assistant.final") < order.index("tts.end")


def test_cancel_by_message_id_stops_the_speech_without_end(tmp_path: Path) -> None:
    tts = GatedTts()
    with build_test_app(tmp_path, turns=[TWO], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "tts.chunk.meta")
            message_id = seen[-1]["message_id"]
            send(ws, "cancel", {"message_id": message_id})
            rest = drain_mixed(ws, "tts.cancelled")
            send(ws, "cancel", {"message_id": message_id})
            again = ws.receive_json()
            send(ws, "cancel", {})
            neither = ws.receive_json()
            tts.release()
            settle(client)
            send(ws, "set_mode", {"reply_mode": "loud"})
            after = ws.receive_json()

    assert rest[-1]["payload"] == {"message_id": message_id}
    assert "tts.end" not in types(rest) and types(rest).count("tts.chunk.meta") <= 1
    assert (
        again["payload"]["code"] == "unknown_task" and neither["payload"]["code"] == "unknown_task"
    )
    assert after["payload"]["code"] == "invalid_reply_mode"
    assert len(tts.sentences) <= 2


def test_cancel_of_an_unknown_message_is_unknown_task(tmp_path: Path) -> None:
    with build_test_app(tmp_path, voice=voice()) as client:
        with open_chat(client) as (ws, _):
            send(ws, "cancel", {"message_id": "nope"})
            error = ws.receive_json()

    assert error["payload"]["code"] == "unknown_task" and "nope" in error["payload"]["detail"]


@pytest.mark.parametrize(
    ("type_", "payload"), [("audio.start", AUDIO_START), ("user.text", {"text": "otra"})]
)
def test_a_new_user_intervention_cancels_the_speech_first(
    tmp_path: Path, type_: str, payload: dict[str, Any]
) -> None:
    tts = GatedTts()
    with build_test_app(tmp_path, turns=[TWO, "Vale."], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            drain_mixed(ws, "tts.chunk.meta")
            send(ws, type_, payload)
            seen = drain_mixed(ws, "tts.cancelled")
            tts.release()
            if type_ == "user.text":
                after = drain_until(ws, "assistant.final")
                assert after[0]["type"] == "user.accepted"
            else:
                settle(client)
                assert client.app.state.hub.audio is not None

    assert "tts.end" not in types(seen)


def test_failure_in_the_second_sentence_degrades_to_text(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[TWO], voice=voice(FakeTts(fail_at_sentence=2))) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "tts.cancelled")
            send(ws, "set_mode", {"reply_mode": "loud"})
            after = ws.receive_json()

    order = types(seen)
    assert "tts.start" in order and 0 < order.count("bin") <= 2 and "tts.end" not in order
    assert order[-2:] == ["error", "tts.cancelled"]
    error = envelopes(seen, "error")[0]["payload"]
    assert error["code"] == "tts_failed" and "frase 2" in error["detail"]
    assert envelopes(seen, "assistant.final")[0]["payload"]["display_text"] == TWO["display_text"]
    assert after["payload"]["code"] == "invalid_reply_mode"


def test_an_engine_that_fails_to_load_reports_tts_failed_without_start(tmp_path: Path) -> None:
    def broken(alias: object, threads: int) -> Tts:
        raise RuntimeError("espeak-ng no encontrado")

    with build_test_app(tmp_path, turns=[TWO], voice=voice(loader=broken)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "error")

    assert types(seen) == ["user.accepted", "usage", "assistant.final", "error"]
    assert seen[-1]["payload"]["code"] == "tts_failed"
    assert "espeak-ng" in seen[-1]["payload"]["detail"]


def test_the_session_log_records_the_synthesis_without_text_or_audio(tmp_path: Path) -> None:
    with build_test_app(tmp_path, turns=[TWO], voice=voice()) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "/v hora"})
            drain_mixed(ws, "tts.end")
            settle(client)

    log = next((tmp_path / "logs").rglob(f"chat-{conversation}.jsonl"))
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    tts = [r["payload"] for r in records if r["type"] == "tts"]
    assert tts == [{"sentences": 2, "duration_ms": 600 + 160, "cancelled": False}]


def test_aclose_during_a_spoken_reply_cancels_and_closes_1001(tmp_path: Path) -> None:
    tts = GatedTts()
    with build_test_app(tmp_path, turns=[TWO], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hora"})
            drain_mixed(ws, "tts.chunk.meta")
            client.portal.call(client.app.state.hub.aclose)
            seen = drain_mixed(ws, "tts.cancelled")
            with pytest.raises(WebSocketDisconnect) as info:
                ws.receive_json()
            tts.release()

    assert "tts.end" not in types(seen) and info.value.code == 1001


def test_reconnection_replays_envelopes_but_never_binary_frames(tmp_path: Path) -> None:
    tts = GatedTts()
    with build_test_app(tmp_path, turns=[TWO], voice=voice(tts)) as client:
        with open_chat(client) as (ws, conversation):
            send(ws, "user.text", {"text": "/v hora"})
            seen = drain_mixed(ws, "bin")
            last_seq = max(m["seq"] for m in seen if isinstance(m, dict))
        wait_detached(client)
        tts.release()
        for _ in range(20):
            settle(client)
        with client.websocket_connect("/ws/chat") as ws2:
            ok = hello(ws2, conversation, last_seq=last_seq)
            replayed = drain_mixed(ws2, "tts.end")

    assert ok["type"] == "hello.ok"
    assert [m["seq"] for m in replayed] == list(range(last_seq + 1, ok["payload"]["last_seq"] + 1))
    assert "bin" not in types(replayed)
    assert types(replayed).count("tts.chunk.meta") >= 2


SECRET = "sk-test-0123456789abcdef"


async def test_review05_finding_1_a_secret_in_the_reply_never_reaches_the_tts() -> None:
    from tests.fakes.sinks import ListEventSink
    from tony.apps.web.protocol import ConversationStream
    from tony.apps.web.tts_stream import SpeechStreamer
    from tony.core.channels.ports import AssistantReply
    from tony.core.voice.cleanup import SPOKEN_MASK
    from tony.core.voice.executor import VoiceExecutor

    tts, executor = FakeTts(), VoiceExecutor()
    stream = ConversationStream("c1", secrets=[SECRET])
    streamer = SpeechStreamer(stream, lambda: tts, executor, "ef_dora", ListEventSink())
    try:
        streamer.start(AssistantReply(f"Tu clave es {SECRET}.", None, "voice", "m1"))
        streamer.on_delta("m2", f"La clave es {SECRET[:9]}")
        streamer.on_delta("m2", f"{SECRET[9:]}. Guárdala.")
        streamer.start(AssistantReply("ignorado", None, "voice", "m2"))
        streamer.start(AssistantReply("Hola.", f"Dice {SECRET} ahora.", "voice", "m3"))
        for _ in range(100):
            if not streamer.speaking:
                break
            await asyncio.sleep(0.02)
    finally:
        await streamer.aclose()
        executor.close()

    spoken = " ".join(tts.sentences)
    assert SECRET not in spoken and SECRET[:9] not in spoken
    assert "***" not in spoken
    assert spoken.count(SPOKEN_MASK) == 3


def test_the_first_spoken_piece_is_cut_at_the_first_clause(tmp_path: Path) -> None:
    tts = FakeTts()
    turn = {
        "display_text": "Buenas tardes, señor. Todo en orden.",
        "speech_text": "Buenas tardes, señor. Todo en orden.",
    }
    with build_test_app(tmp_path, turns=[turn], voice=voice(tts)) as client:
        with open_chat(client) as (ws, _):
            send(ws, "user.text", {"text": "/v hola"})
            drain_mixed(ws, "tts.end")

    assert tts.sentences == ["Buenas tardes,", "señor.", "Todo en orden."]
