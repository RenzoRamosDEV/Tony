"""WebSocket protocol v1 of `/ws/chat`: envelopes, limits, per-conversation seq, bounded queue."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 32 * 1024
BUFFER_SIZE = 500
QUEUE_CAPACITY = 500

HELLO = "hello"
USER_TEXT = "user.text"
CONFIRM = "confirm"
CANCEL = "cancel"
SET_MODE = "set_mode"
CLIENT_TYPES = frozenset({HELLO, USER_TEXT, CONFIRM, CANCEL, SET_MODE})
AUDIO_TYPES = frozenset({"audio.start", "audio.chunk", "audio.end"})

HELLO_OK = "hello.ok"
USER_ACCEPTED = "user.accepted"
ASSISTANT_DELTA = "assistant.delta"
ASSISTANT_WAIT = "assistant.wait"
ASSISTANT_FINAL = "assistant.final"
USAGE = "usage"
ERROR = "error"

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


class NotImplementedType(ProtocolError):
    code = "not_implemented"


class UnknownType(ProtocolError):
    code = "unknown_type"


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
    if envelope.type in AUDIO_TYPES:
        raise NotImplementedType(f"el tipo {envelope.type} está reservado para la entrega de voz")
    if envelope.type not in CLIENT_TYPES:
        raise UnknownType(f"tipo desconocido: {envelope.type}")
    return ClientMessage(envelope.type, envelope.payload, envelope.seq)


def _brief(exc: Exception) -> str:
    return str(exc).splitlines()[0]


def coalesce_deltas(items: Iterable[Envelope]) -> list[Envelope]:
    """Merge the deltas of each message into one placed where its last delta was."""
    texts: dict[str | None, list[str]] = {}
    last_delta: dict[str | None, Envelope] = {}
    for item in items:
        if item.type == ASSISTANT_DELTA:
            texts.setdefault(item.message_id, []).append(item.payload.get("text", ""))
            last_delta[item.message_id] = item
    merged: list[Envelope] = []
    for item in items:
        if item.type != ASSISTANT_DELTA:
            merged.append(item)
        elif last_delta[item.message_id] is item:
            text = "".join(texts[item.message_id])
            merged.append(item.model_copy(update={"payload": {**item.payload, "text": text}}))
    return merged


class OutboundQueue:
    """Bounded per-socket queue: when full it merges pending deltas, then applies backpressure."""

    def __init__(self, capacity: int = QUEUE_CAPACITY) -> None:
        self._capacity = capacity
        self._items: deque[Envelope] = deque()
        self._not_empty = asyncio.Event()
        self._not_full = asyncio.Event()
        self._not_full.set()

    def __len__(self) -> int:
        return len(self._items)

    def prefill(self, envelopes: Iterable[Envelope]) -> None:
        """Seed the queue with replayed envelopes before any live one is published."""
        self._items.extend(envelopes)
        if self._items:
            self._not_empty.set()

    async def put(self, envelope: Envelope) -> None:
        if len(self._items) >= self._capacity:
            self._items = deque(coalesce_deltas(list(self._items)))
        while len(self._items) >= self._capacity:
            self._not_full.clear()
            await self._not_full.wait()
        self._items.append(envelope)
        self._not_empty.set()

    async def get(self) -> Envelope:
        while not self._items:
            self._not_empty.clear()
            await self._not_empty.wait()
        item = self._items.popleft()
        self._not_full.set()
        return item


class ConversationStream:
    """Numbers every server envelope of one conversation and keeps the last ones for replay."""

    def __init__(self, conversation_id: str, buffer_size: int = BUFFER_SIZE) -> None:
        self.conversation_id = conversation_id
        self.last_seq = 0
        self._buffer: deque[Envelope] = deque(maxlen=buffer_size)
        self._queue: OutboundQueue | None = None

    def attach(self, queue: OutboundQueue) -> None:
        self._queue = queue

    def detach(self) -> None:
        self._queue = None

    async def publish(
        self,
        type_: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        message_id: str | None = None,
    ) -> Envelope:
        self.last_seq += 1
        envelope = Envelope(
            type=type_,
            seq=self.last_seq,
            conversation_id=self.conversation_id,
            message_id=message_id,
            task_id=task_id,
            payload=payload,
        )
        self._buffer.append(envelope)
        if self._queue is not None:
            await self._queue.put(envelope)
        return envelope

    def replay(self, last_seq: int) -> list[Envelope] | None:
        """Envelopes after `last_seq`, or None when they are older than the buffer (resync)."""
        if self._buffer and last_seq < self._buffer[0].seq - 1:
            return None
        return [envelope for envelope in self._buffer if envelope.seq > last_seq]
