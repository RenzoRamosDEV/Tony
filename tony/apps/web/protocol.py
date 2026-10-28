"""WebSocket protocol v1 of `/ws/chat`: envelopes, limits, per-conversation seq, bounded queue."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tony.core.logging import redact

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 32 * 1024
BUFFER_SIZE = 500
QUEUE_CAPACITY = 500

HELLO = "hello"
USER_TEXT = "user.text"
CONFIRM = "confirm"
CANCEL = "cancel"
SET_MODE = "set_mode"
AUDIO_START = "audio.start"
AUDIO_END = "audio.end"
CLIENT_TYPES = frozenset({HELLO, USER_TEXT, CONFIRM, CANCEL, SET_MODE, AUDIO_START, AUDIO_END})
AUDIO_FRAME_MAX_BYTES = 16 * 1024
SUPPORTED_AUDIO = {"sample_rate": 16000, "channels": 1, "format": "f32"}

HELLO_OK = "hello.ok"
USER_ACCEPTED = "user.accepted"
ASSISTANT_DELTA = "assistant.delta"
ASSISTANT_WAIT = "assistant.wait"
ASSISTANT_FINAL = "assistant.final"
USAGE = "usage"
ERROR = "error"
STT_FINAL = "stt.final"
TTS_START = "tts.start"
TTS_CHUNK_META = "tts.chunk.meta"
TTS_END = "tts.end"
TTS_CANCELLED = "tts.cancelled"

CLOSE_POLICY_VIOLATION = 1008
CLOSE_TOO_LARGE = 1009
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_GOING_AWAY = 1001


class ProtocolError(Exception):
    code = "protocol_error"
    close_code: int | None = None

    def __init__(self, detail: str, close_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if close_code is not None:
            self.close_code = close_code


class MessageTooLarge(ProtocolError):
    code = "message_too_large"
    close_code = CLOSE_TOO_LARGE


class BadEnvelope(ProtocolError):
    code = "bad_envelope"


class UnsupportedAudio(ProtocolError):
    code = "unsupported_audio"


class UnknownType(ProtocolError):
    code = "unknown_type"


class BadPayload(ProtocolError):
    code = "bad_payload"


class QueueClosed(Exception):
    """The socket of this queue is gone: nothing more can be put or taken."""


class Envelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    v: int = PROTOCOL_VERSION
    type: str
    seq: int
    conversation_id: str | None
    message_id: str | None = None
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        data = self.model_dump()
        for optional in ("message_id", "task_id"):
            if data[optional] is None:
                del data[optional]
        return json.dumps(data, ensure_ascii=False)


@dataclass(frozen=True)
class BinaryFrame:
    """Audio of one reply, queued right behind its `tts.chunk.meta`; never numbered nor replayed."""

    data: bytes
    message_id: str


QueueItem = Envelope | BinaryFrame


@dataclass(frozen=True)
class ClientMessage:
    type: str
    payload: dict[str, Any]
    seq: int


class _ClientEnvelope(BaseModel):
    v: int
    type: str
    seq: int = 0
    conversation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class _StrictPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _HelloPayload(_StrictPayload):
    conversation_id: str | None = None
    last_seq: int = Field(default=0, ge=0)


class _UserTextPayload(_StrictPayload):
    text: str
    client_id: str | None = None


class _ConfirmPayload(_StrictPayload):
    confirmation_id: str
    approved: bool
    task_id: str | None = None


class _CancelPayload(_StrictPayload):
    task_id: str | None = None
    message_id: str | None = None


class _SetModePayload(_StrictPayload):
    reply_mode: str


class _AudioStartPayload(_StrictPayload):
    sample_rate: int = SUPPORTED_AUDIO["sample_rate"]
    channels: int = SUPPORTED_AUDIO["channels"]
    format: str = SUPPORTED_AUDIO["format"]


class _AudioEndPayload(_StrictPayload):
    pass


PAYLOAD_MODELS: dict[str, type[_StrictPayload]] = {
    HELLO: _HelloPayload,
    USER_TEXT: _UserTextPayload,
    CONFIRM: _ConfirmPayload,
    CANCEL: _CancelPayload,
    SET_MODE: _SetModePayload,
    AUDIO_START: _AudioStartPayload,
    AUDIO_END: _AudioEndPayload,
}


def validate_audio_start(payload: dict[str, Any]) -> str | None:
    """Why an `audio.start` payload is not the one supported format, or None when it is."""
    if all(payload.get(key) == value for key, value in SUPPORTED_AUDIO.items()):
        return None
    given = ", ".join(f"{key}={payload.get(key)!r}" for key in SUPPORTED_AUDIO)
    supported = ", ".join(f"{key}={value!r}" for key, value in SUPPORTED_AUDIO.items())
    return f"formato de audio no soportado ({given}); se requiere {supported}"


def parse_client_message(text: str) -> ClientMessage:
    size = len(text.encode("utf-8"))
    if size > MAX_MESSAGE_BYTES:
        raise MessageTooLarge(f"mensaje de {size} bytes; el máximo es {MAX_MESSAGE_BYTES}")
    try:
        raw = json.loads(text)
        envelope = _ClientEnvelope.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise BadEnvelope(f"sobre inválido: {_brief(exc)}") from None
    if envelope.v != PROTOCOL_VERSION:
        raise BadEnvelope(
            f"versión {envelope.v} no soportada; se requiere v: {PROTOCOL_VERSION}",
            close_code=CLOSE_PROTOCOL_ERROR,
        )
    if envelope.type not in CLIENT_TYPES:
        raise UnknownType(f"tipo desconocido: {envelope.type}")
    try:
        payload = PAYLOAD_MODELS[envelope.type].model_validate(envelope.payload).model_dump()
    except ValidationError as exc:
        raise BadPayload(f"payload inválido para {envelope.type}: {_brief(exc)}") from None
    if envelope.type == AUDIO_START and (problem := validate_audio_start(payload)) is not None:
        raise UnsupportedAudio(problem)
    return ClientMessage(envelope.type, payload, envelope.seq)


def _brief(exc: Exception) -> str:
    return str(exc).splitlines()[0]


def coalesce_deltas(items: Iterable[QueueItem]) -> list[QueueItem]:
    """Merge the deltas of each message into one placed where its last delta was."""
    texts: dict[str | None, list[str]] = {}
    last_delta: dict[str | None, Envelope] = {}
    for item in items:
        if isinstance(item, Envelope) and item.type == ASSISTANT_DELTA:
            texts.setdefault(item.message_id, []).append(item.payload.get("text", ""))
            last_delta[item.message_id] = item
    merged: list[QueueItem] = []
    for item in items:
        if not isinstance(item, Envelope) or item.type != ASSISTANT_DELTA:
            merged.append(item)
        elif last_delta[item.message_id] is item:
            text = "".join(texts[item.message_id])
            merged.append(item.model_copy(update={"payload": {**item.payload, "text": text}}))
    return merged


class OutboundQueue:
    """Bounded per-socket queue: when full it merges pending deltas, then applies backpressure."""

    def __init__(self, capacity: int = QUEUE_CAPACITY) -> None:
        self._capacity = capacity
        self._items: deque[QueueItem] = deque()
        self._not_empty = asyncio.Event()
        self._not_full = asyncio.Event()
        self._not_full.set()
        self._empty = asyncio.Event()
        self._empty.set()
        self._in_flight = 0
        self._closed = False

    def __len__(self) -> int:
        return len(self._items)

    async def drained(self) -> None:
        """Wait until the consumer has sent everything queued so far (or the queue closes)."""
        while (self._items or self._in_flight) and not self._closed:
            self._empty.clear()
            await self._empty.wait()

    def done(self) -> None:
        """The consumer finished sending the item it last took."""
        self._in_flight = max(0, self._in_flight - 1)
        if not self._items and not self._in_flight:
            self._empty.set()

    def close(self) -> None:
        """Wake every blocked producer and consumer; later puts and gets raise QueueClosed."""
        self._closed = True
        self._not_full.set()
        self._not_empty.set()
        self._empty.set()

    def prefill(self, envelopes: Iterable[Envelope]) -> None:
        """Seed the queue with replayed envelopes before any live one is published."""
        self._items.extend(envelopes)
        if self._items:
            self._not_empty.set()

    def purge(self, message_id: str) -> int:
        """Drop the audio still queued for one reply (its `tts.chunk.meta` and binary frames)."""
        kept = deque(item for item in self._items if not _is_audio_of(item, message_id))
        removed = len(self._items) - len(kept)
        self._items = kept
        if len(self._items) < self._capacity:
            self._not_full.set()
        if not self._items and not self._in_flight:
            self._empty.set()
        return removed

    async def put(self, envelope: QueueItem) -> None:
        if len(self._items) >= self._capacity:
            self._items = deque(coalesce_deltas(list(self._items)))
        while len(self._items) >= self._capacity and not self._closed:
            self._not_full.clear()
            await self._not_full.wait()
        if self._closed:
            raise QueueClosed
        self._items.append(envelope)
        self._not_empty.set()

    async def get(self) -> QueueItem:
        while not self._items:
            if self._closed:
                raise QueueClosed
            self._not_empty.clear()
            await self._not_empty.wait()
        item = self._items.popleft()
        self._in_flight += 1
        self._not_full.set()
        return item


def _is_audio_of(item: QueueItem, message_id: str) -> bool:
    if isinstance(item, BinaryFrame):
        return item.message_id == message_id
    return item.type == TTS_CHUNK_META and item.message_id == message_id


class ConversationStream:
    """Numbers every server envelope of one conversation and keeps the last ones for replay."""

    def __init__(
        self,
        conversation_id: str,
        buffer_size: int = BUFFER_SIZE,
        secrets: Iterable[str] = (),
    ) -> None:
        self.conversation_id = conversation_id
        self.stream_id = uuid.uuid4().hex
        self.last_seq = 0
        self._secrets = list(secrets)
        self._buffer: deque[Envelope] = deque(maxlen=buffer_size)
        self._queue: OutboundQueue | None = None
        self._publishing = asyncio.Lock()

    def attach(self, queue: OutboundQueue) -> None:
        self._queue = queue

    def detach(self) -> None:
        queue, self._queue = self._queue, None
        if queue is not None:
            queue.close()

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return redact(payload, self._secrets)

    def redact_text(self, text: str) -> str:
        return redact(text, self._secrets)

    async def publish(
        self,
        type_: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        message_id: str | None = None,
    ) -> Envelope:
        async with self._publishing:
            self.last_seq += 1
            envelope = Envelope(
                type=type_,
                seq=self.last_seq,
                conversation_id=self.conversation_id,
                message_id=message_id,
                task_id=task_id,
                payload=self.redact(payload),
            )
            self._buffer.append(envelope)
            if self._queue is not None:
                with contextlib.suppress(QueueClosed):
                    await self._queue.put(envelope)
        return envelope

    async def publish_binary(self, data: bytes, message_id: str) -> BinaryFrame:
        """Queue audio behind whatever was published before it; it takes no seq and no buffer."""
        frame = BinaryFrame(data, message_id)
        async with self._publishing:
            if self._queue is not None:
                with contextlib.suppress(QueueClosed):
                    await self._queue.put(frame)
        return frame

    def purge_audio(self, message_id: str) -> int:
        return self._queue.purge(message_id) if self._queue is not None else 0

    def replay(self, last_seq: int) -> list[Envelope] | None:
        """Envelopes after `last_seq`, or None when they are older than the buffer (resync)."""
        if self._buffer and last_seq < self._buffer[0].seq - 1:
            return None
        return [envelope for envelope in self._buffer if envelope.seq > last_seq]
