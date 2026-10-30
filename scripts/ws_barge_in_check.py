"""Manual check: talking over Tony cancels the current speech and starts a new turn.

    uv run --extra web --extra voice python scripts/ws_barge_in_check.py [--port 8787]

Requires the server already running (`uv run tony web`). Triggers a long spoken reply,
and once `tts.chunk`s start flowing, streams a second utterance (synthesized with Tony's
own TTS) as if the user spoke over it. Verifies `tts.cancelled` for the first reply and a
fresh `stt.final` / `user.accepted` for the second.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets
from _ws_common import FRAME_MS, WS_URL, envelope, frames, silence_frame, synthesize_utterance

LONG_PROMPT = "Cuéntame con detalle qué puedes hacer, en al menos tres frases."
INTERRUPTION = "¿qué hora es?"
TRAILING_SILENCE_MS = 700


async def stream_audio(ws, pcm: bytes, conversation_id: str) -> None:
    await ws.send(
        envelope(
            "audio.start", {"sample_rate": 16_000, "channels": 1, "format": "f32"}, conversation_id
        )
    )
    frame_s = FRAME_MS / 1_000
    for frame in frames(pcm):
        await ws.send(frame)
        await asyncio.sleep(frame_s)
    for _ in range(TRAILING_SILENCE_MS // FRAME_MS):
        await ws.send(silence_frame())
        await asyncio.sleep(frame_s)
    await ws.send(envelope("audio.end", {}, conversation_id))


async def run(port: int) -> None:
    print(f"Sintetizando la interrupción {INTERRUPTION!r}...")
    interruption_pcm = synthesize_utterance(INTERRUPTION)

    url = WS_URL.format(port=port)
    origin = f"http://127.0.0.1:{port}"
    async with websockets.connect(url, max_size=None, additional_headers={"Origin": origin}) as ws:
        await ws.send(envelope("hello", {"conversation_id": None}))
        hello_ok = json.loads(await ws.recv())
        conversation_id = hello_ok["payload"]["conversation_id"]
        print("<- hello.ok", conversation_id)

        await ws.send(envelope("user.text", {"text": LONG_PROMPT}, conversation_id))

        events: list[str] = []
        first_message_id: str | None = None
        barge_in_sent = False
        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                if not barge_in_sent and "tts.chunk.meta" in events:
                    barge_in_sent = True
                    print(f"[primer chunk recibido, hablando encima con {INTERRUPTION!r}]")
                    asyncio.create_task(stream_audio(ws, interruption_pcm, conversation_id))
                continue
            data = json.loads(message)
            msg_type = data["type"]
            payload = data.get("payload", {})
            events.append(msg_type)
            print("<-", msg_type, payload if msg_type not in ("usage", "assistant.delta") else "")
            if msg_type == "tts.start" and first_message_id is None:
                first_message_id = payload.get("message_id")
            if msg_type == "stt.final" and barge_in_sent:
                break
            if len(events) > 80:
                print("Demasiados eventos sin llegar a una conclusión; abortando.")
                break

        print(f"\nSecuencia: {' -> '.join(events)}")
        got_cancel = (
            "tts.cancelled" in events[events.index("tts.start") :]
            if "tts.start" in events
            else False
        )
        got_new_turn = events.count("stt.final") >= 2 or (
            "stt.final" in events and events[-1] in ("stt.final", "user.accepted")
        )
        print("tts.cancelled tras hablar encima:", got_cancel)
        print("nuevo stt.final / user.accepted tras la interrupción:", got_new_turn)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    asyncio.run(run(args.port))


if __name__ == "__main__":
    main()
