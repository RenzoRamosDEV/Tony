"""Manual check: end of speech -> first spoken audio, over a real running `tony web` server.

    uv run --extra web --extra voice python scripts/ws_realtime_check.py [--port 8787]

Requires the server already running (`uv run tony web`). Synthesizes "¿qué hora es?" with
Tony's own TTS, streams it as real-time `audio.chunk` frames plus 700 ms of trailing
silence, and times from the last frame carrying speech to the first `tts.chunk.meta` /
first binary audio frame. Prints the event sequence received.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets
from _ws_common import (
    FRAME_MS,
    WS_URL,
    envelope,
    frames,
    silence_frame,
    synthesize_utterance,
)

TEXT = "¿qué hora es?"
TRAILING_SILENCE_MS = 700


async def run(port: int) -> None:
    print(f"Sintetizando {TEXT!r} con la voz configurada...")
    pcm = synthesize_utterance(TEXT)
    speech_frames = frames(pcm)
    silence_frames = [silence_frame() for _ in range(TRAILING_SILENCE_MS // FRAME_MS)]
    print(f"{len(speech_frames)} frames de habla + {len(silence_frames)} de silencio")

    url = WS_URL.format(port=port)
    origin = f"http://127.0.0.1:{port}"
    async with websockets.connect(url, max_size=None, additional_headers={"Origin": origin}) as ws:
        await ws.send(envelope("hello", {"conversation_id": None}))
        hello_ok = json.loads(await ws.recv())
        print("<-", hello_ok["type"], hello_ok.get("payload", {}).get("conversation_id"))
        conversation_id = hello_ok["payload"]["conversation_id"]

        await ws.send(
            envelope(
                "audio.start",
                {"sample_rate": 16_000, "channels": 1, "format": "f32"},
                conversation_id,
            )
        )

        async def send_audio() -> float:
            last_speech_sent = 0.0
            frame_s = FRAME_MS / 1_000
            next_due = time.monotonic()
            for frame in speech_frames:
                next_due += frame_s
                await ws.send(frame)
                last_speech_sent = time.monotonic()
                sleep_for = next_due - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            for frame in silence_frames:
                next_due += frame_s
                await ws.send(frame)
                sleep_for = next_due - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            await ws.send(envelope("audio.end", {}, conversation_id))
            return last_speech_sent

        send_task = asyncio.create_task(send_audio())

        first_audio_at: float | None = None
        seen_types: list[str] = []
        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                if first_audio_at is None:
                    first_audio_at = time.monotonic()
                    print(f"<- [binario {len(message)} bytes] (primer audio)")
                continue
            data = json.loads(message)
            msg_type = data["type"]
            seen_types.append(msg_type)
            print("<-", msg_type, data.get("payload", {}) if msg_type != "usage" else "")
            if msg_type == "tts.end" or msg_type == "assistant.final" and "tts.end" in seen_types:
                break
            if msg_type == "error":
                break

        last_speech_sent = await send_task
        if first_audio_at is not None:
            elapsed_ms = int((first_audio_at - last_speech_sent) * 1_000)
            print(f"\nFin de habla -> primer audio: {elapsed_ms} ms")
        else:
            print("\nNo llegó audio (revisa la secuencia de arriba).")

        sequence = " -> ".join(seen_types)
        print(f"Secuencia: {sequence}")
        expected = ["stt.final", "user.accepted"]
        got_expected = all(e in seen_types for e in expected) and "tts.start" in seen_types
        print(
            "Secuencia esperada presente:" if got_expected else "FALTA en la secuencia:",
            got_expected,
        )
        if "assistant.final" in seen_types and "tts.chunk.meta" in seen_types:
            final_idx = seen_types.index("assistant.final")
            chunk_idx = seen_types.index("tts.chunk.meta")
            before = chunk_idx < final_idx
            print(
                "El primer tts.chunk.meta llega antes de assistant.final:"
                if before
                else "El primer tts.chunk.meta llega DESPUÉS de assistant.final"
                " (streaming de voz no se activó en este turno; revisa el log del servidor):",
                before,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    asyncio.run(run(args.port))


if __name__ == "__main__":
    main()
