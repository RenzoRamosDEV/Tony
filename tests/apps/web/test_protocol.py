"""WS protocol v1: envelope parsing and limits, per-conversation seq, replay, bounded queue."""

from __future__ import annotations

import asyncio
import json

import pytest

from tony.apps.web.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    BadEnvelope,
    BadPayload,
    BinaryFrame,
    ConversationStream,
    Envelope,
    MessageTooLarge,
    OutboundQueue,
    ProtocolError,
    QueueClosed,
    UnknownType,
    UnsupportedAudio,
    coalesce_deltas,
    parse_client_message,
    validate_audio_start,
)


def envelope_of(size: int, type_: str = "user.text") -> str:
    base = {"v": 1, "type": type_, "seq": 1, "conversation_id": "c1", "payload": {"text": ""}}
    padding = size - len(json.dumps(base).encode("utf-8"))
    base["payload"]["text"] = "a" * padding
    text = json.dumps(base)
    assert len(text.encode("utf-8")) == size
    return text


def test_envelope_at_the_limit_is_accepted_and_one_byte_more_rejected() -> None:
    assert MAX_MESSAGE_BYTES == 32768
    message = parse_client_message(envelope_of(32768))
    assert message.type == "user.text" and message.seq == 1
    assert len(message.payload["text"]) > 32000

    with pytest.raises(MessageTooLarge) as info:
        parse_client_message(envelope_of(32769))
    assert info.value.code == "message_too_large" and info.value.close_code == 1009
    assert "32769" in info.value.detail and "32768" in info.value.detail


def test_wrong_version_is_a_bad_envelope_that_closes() -> None:
    with pytest.raises(BadEnvelope) as info:
        parse_client_message(
            '{"v": 2, "type": "hello", "seq": 1, "conversation_id": null, "payload": {}}'
        )
    assert info.value.code == "bad_envelope" and info.value.close_code == 1002
    assert "2" in info.value.detail


@pytest.mark.parametrize(
    "text",
    ["{not json", '{"v": 1, "seq": 1, "payload": {}}', "[]", '{"v": 1, "type": 3, "payload": {}}'],
)
def test_invalid_json_or_missing_type_is_a_bad_envelope_without_closing(text: str) -> None:
    with pytest.raises(BadEnvelope) as info:
        parse_client_message(text)
    assert info.value.code == "bad_envelope" and info.value.close_code is None
    assert info.value.detail.startswith("sobre inválido: ") and len(info.value.detail) > 16
    assert "\n" not in info.value.detail


def test_audio_start_and_end_are_client_types_and_audio_chunk_is_not() -> None:
    start = parse_client_message(client_text("audio.start", {}))
    end = parse_client_message(client_text("audio.end", {}))

    assert start.payload == {"sample_rate": 16000, "channels": 1, "format": "f32"}
    assert end.type == "audio.end" and end.payload == {}
    with pytest.raises(UnknownType):
        parse_client_message(client_text("audio.chunk", {}))


@pytest.mark.parametrize(
    "payload",
    [
        {"sample_rate": 44100, "channels": 2, "format": "f32"},
        {"sample_rate": 48000},
        {"channels": 2},
        {"format": "i16"},
    ],
)
def test_audio_start_with_other_parameters_is_unsupported_without_closing(payload) -> None:
    with pytest.raises(UnsupportedAudio) as info:
        parse_client_message(client_text("audio.start", payload))

    assert info.value.code == "unsupported_audio" and info.value.close_code is None
    assert "16000" in info.value.detail and "f32" in info.value.detail


@pytest.mark.parametrize(
    ("payload", "ok"),
    [
        ({"sample_rate": 16000, "channels": 1, "format": "f32"}, True),
        ({"sample_rate": 16001, "channels": 1, "format": "f32"}, False),
        ({"sample_rate": 16000, "channels": 0, "format": "f32"}, False),
        ({"sample_rate": 16000, "channels": 1, "format": "F32"}, False),
    ],
)
def test_validate_audio_start_table(payload, ok: bool) -> None:
    assert (validate_audio_start(payload) is None) is ok


def test_unknown_type_is_reported() -> None:
    with pytest.raises(UnknownType) as info:
        parse_client_message(envelope_of(200, "ping"))
    assert info.value.code == "unknown_type" and "ping" in info.value.detail


def test_payload_defaults_to_an_empty_object_and_seq_is_optional() -> None:
    message = parse_client_message('{"v": 1, "type": "hello", "conversation_id": null}')
    assert message.payload == {"conversation_id": None, "last_seq": 0} and message.seq == 0


async def test_publish_numbers_seq_and_builds_the_envelope_without_none_keys() -> None:
    stream = ConversationStream("c1")

    first = await stream.publish("hello.ok", {"conversation_id": "c1"})
    second = await stream.publish("assistant.delta", {"text": "Hola"}, message_id="m1")
    third = await stream.publish("task.queued", {"objetivo": "x"}, task_id="t1")

    assert [e.seq for e in (first, second, third)] == [1, 2, 3]
    assert stream.last_seq == 3
    assert json.loads(first.to_json()) == {
        "v": PROTOCOL_VERSION,
        "type": "hello.ok",
        "seq": 1,
        "conversation_id": "c1",
        "payload": {"conversation_id": "c1"},
    }
    assert list(json.loads(second.to_json())) == [
        "v",
        "type",
        "seq",
        "conversation_id",
        "message_id",
        "payload",
    ]
    assert json.loads(third.to_json())["task_id"] == "t1"
    assert "message_id" not in json.loads(third.to_json())
    accented = await stream.publish("assistant.wait", {"text": "señor"})
    assert '"señor"' in accented.to_json()


async def test_replay_returns_only_the_envelopes_after_last_seq() -> None:
    stream = ConversationStream("c1")
    for i in range(25):
        await stream.publish("task.progress", {"step": i})

    replayed = stream.replay(18)

    assert replayed is not None
    assert [e.seq for e in replayed] == list(range(19, 26))
    assert stream.replay(25) == []
    assert stream.replay(0) is not None and len(stream.replay(0)) == 25


async def test_replay_older_than_the_buffer_requests_a_resync() -> None:
    stream = ConversationStream("c1", buffer_size=500)
    for i in range(700):
        await stream.publish("task.progress", {"step": i})

    assert stream.replay(10) is None
    assert stream.replay(199) is None
    assert stream.replay(200) is not None and len(stream.replay(200)) == 500
    assert ConversationStream("c2").replay(0) == []


def delta(seq: int, message_id: str, text: str) -> Envelope:
    return Envelope(
        type="assistant.delta",
        seq=seq,
        conversation_id="c1",
        message_id=message_id,
        payload={"text": text},
    )


def task(seq: int, type_: str = "task.progress") -> Envelope:
    return Envelope(type=type_, seq=seq, conversation_id="c1", task_id="t1", payload={"seq": seq})


def test_coalesce_merges_deltas_per_message_at_the_position_of_the_last_one() -> None:
    items = [
        delta(1, "a", "Ho"),
        task(2),
        delta(3, "b", "x"),
        delta(4, "a", "la"),
        task(5),
        delta(6, "b", "y"),
    ]

    merged = coalesce_deltas(items)

    assert [(e.type, e.seq) for e in merged] == [
        ("task.progress", 2),
        ("assistant.delta", 4),
        ("task.progress", 5),
        ("assistant.delta", 6),
    ]
    assert merged[1].payload == {"text": "Hola"} and merged[1].message_id == "a"
    assert merged[3].payload == {"text": "xy"} and merged[3].message_id == "b"
    assert coalesce_deltas([]) == []
    assert coalesce_deltas([task(1)]) == [task(1)]
    missing_text = Envelope(type="assistant.delta", seq=7, conversation_id="c1", message_id="a")
    assert coalesce_deltas([delta(6, "a", "x"), missing_text])[0].payload == {"text": "x"}


async def test_full_queue_merges_pending_deltas_and_keeps_every_other_event() -> None:
    queue = OutboundQueue(500)
    for i in range(1, 101):
        await queue.put(task(i, "task.queued" if i == 1 else "task.progress"))
    for i in range(101, 501):
        await queue.put(delta(i, "m1", str(i % 10)))
    assert len(queue) == 500

    await queue.put(task(501, "task.result"))

    assert len(queue) == 102
    drained = [await queue.get() for _ in range(102)]
    assert [e.seq for e in drained[:100]] == list(range(1, 101))
    assert drained[0].type == "task.queued"
    assert drained[100].type == "assistant.delta" and drained[100].seq == 500
    assert drained[100].payload["text"] == "".join(str(i % 10) for i in range(101, 501))
    assert drained[101].type == "task.result" and drained[101].seq == 501


async def test_full_queue_without_deltas_waits_for_the_consumer() -> None:
    queue = OutboundQueue(3)
    for i in range(1, 4):
        await queue.put(task(i))

    blocked = asyncio.ensure_future(queue.put(task(4)))
    await asyncio.sleep(0)
    assert not blocked.done() and len(queue) == 3

    assert (await queue.get()).seq == 1
    await asyncio.wait_for(blocked, 1)
    assert [(await queue.get()).seq for _ in range(3)] == [2, 3, 4]


async def test_get_waits_for_the_next_item() -> None:
    queue = OutboundQueue(10)
    getter = asyncio.ensure_future(queue.get())
    await asyncio.sleep(0)
    assert not getter.done()

    await queue.put(task(1))

    assert (await asyncio.wait_for(getter, 1)).seq == 1


async def test_stream_feeds_the_attached_queue_only_while_attached() -> None:
    stream = ConversationStream("c1")
    queue = OutboundQueue(10)
    await stream.publish("a", {})
    stream.attach(queue)
    await stream.publish("b", {})
    stream.detach()
    await stream.publish("c", {})

    assert len(queue) == 1 and (await queue.get()).type == "b"
    assert [e.type for e in stream.replay(0) or []] == ["a", "b", "c"]


# --- Review of change 04 ---------------------------------------------------------------

SECRET = "sk-secret-123456"


def client_text(type_: str, payload: dict) -> str:
    return json.dumps(
        {"v": 1, "type": type_, "seq": 1, "conversation_id": None, "payload": payload}
    )


async def test_finding_2_detach_wakes_a_blocked_publisher_instead_of_hanging() -> None:
    stream = ConversationStream("c1")
    queue = OutboundQueue(1)
    stream.attach(queue)
    await stream.publish("a", {})
    blocked = asyncio.ensure_future(stream.publish("b", {}))
    await asyncio.sleep(0)
    assert not blocked.done()

    stream.detach()

    envelope = await asyncio.wait_for(blocked, 1)
    assert envelope.seq == 2 and [e.seq for e in stream.replay(0) or []] == [1, 2]
    with pytest.raises(QueueClosed):
        await asyncio.wait_for(queue.put(task(3)), 1)
    assert (await queue.get()).type == "a"
    with pytest.raises(QueueClosed):
        await asyncio.wait_for(queue.get(), 1)


async def test_finding_3_concurrent_publishers_keep_seq_order_under_backpressure() -> None:
    stream = ConversationStream("c1")
    queue = OutboundQueue(1)
    stream.attach(queue)
    await stream.publish("one", {})
    second = asyncio.ensure_future(stream.publish("two", {}))
    await asyncio.sleep(0)
    assert not second.done()

    third = asyncio.ensure_future(stream.publish("three", {}))
    delivered = [await queue.get()]
    await asyncio.sleep(0)
    delivered.append(await asyncio.wait_for(queue.get(), 1))
    delivered.append(await asyncio.wait_for(queue.get(), 1))
    await asyncio.wait_for(asyncio.gather(second, third), 1)

    assert [(e.seq, e.type) for e in delivered] == [(1, "one"), (2, "two"), (3, "three")]


@pytest.mark.parametrize(
    ("type_", "payload"),
    [
        ("confirm", {"confirmation_id": "c", "approved": "false"}),
        ("confirm", {"confirmation_id": "c", "approved": 1}),
        ("confirm", {"approved": True}),
        ("confirm", {"confirmation_id": 7, "approved": True}),
        ("hello", {"conversation_id": None, "last_seq": "abc"}),
        ("hello", {"conversation_id": None, "last_seq": -1}),
        ("hello", {"conversation_id": None, "last_seq": 1.5}),
        ("hello", {"conversation_id": 3}),
        ("user.text", {}),
        ("user.text", {"text": ["x"]}),
        ("user.text", {"text": "x", "client_id": 9}),
        ("cancel", {"task_id": 1}),
        ("cancel", {"message_id": 1}),
        ("set_mode", {"reply_mode": None}),
        ("audio.start", {"sample_rate": "16000"}),
        ("audio.start", {"channels": 1.0}),
        ("playback.stopped", {}),
        ("playback.stopped", {"message_id": 5}),
        ("playback.stopped", {"message_id": None}),
    ],
)
def test_finding_7_invalid_payloads_are_rejected_before_dispatch(type_: str, payload) -> None:
    with pytest.raises(BadPayload) as info:
        parse_client_message(client_text(type_, payload))

    assert info.value.code == "bad_payload" and info.value.close_code is None
    assert isinstance(info.value, ProtocolError)


@pytest.mark.parametrize(
    ("type_", "payload", "expected"),
    [
        ("hello", {}, {"conversation_id": None, "last_seq": 0}),
        ("hello", {"conversation_id": "c", "last_seq": 0}, {"conversation_id": "c", "last_seq": 0}),
        (
            "confirm",
            {"confirmation_id": "c", "approved": False, "extra": 1},
            {"confirmation_id": "c", "approved": False, "task_id": None},
        ),
        ("user.text", {"text": ""}, {"text": "", "client_id": None}),
        ("user.text", {"text": "hola", "client_id": "r-1"}, {"text": "hola", "client_id": "r-1"}),
        ("cancel", {"task_id": "t"}, {"task_id": "t", "message_id": None}),
        ("cancel", {"message_id": "m"}, {"task_id": None, "message_id": "m"}),
        ("cancel", {}, {"task_id": None, "message_id": None}),
        ("set_mode", {"reply_mode": "nope"}, {"reply_mode": "nope"}),
        ("playback.stopped", {"message_id": "m-2"}, {"message_id": "m-2"}),
    ],
)
def test_finding_7_valid_payloads_are_normalised(type_: str, payload, expected) -> None:
    assert parse_client_message(client_text(type_, payload)).payload == expected


def test_finding_11_each_stream_instance_has_its_own_stable_stream_id() -> None:
    first, again = ConversationStream("c1"), ConversationStream("c1")

    assert first.stream_id == first.stream_id and first.stream_id != again.stream_id
    assert len(first.stream_id) == 32


async def test_finding_1_stream_redacts_secrets_before_buffering_and_queueing() -> None:
    stream = ConversationStream("c1", secrets=[SECRET, "short"])
    queue = OutboundQueue(10)
    stream.attach(queue)

    envelope = await stream.publish(
        "task.needs_confirmation",
        {"args": {"token": "x", "cmd": f"curl -H {SECRET} short"}, "list": [SECRET]},
    )

    expected = {"args": {"token": "***", "cmd": "curl -H *** short"}, "list": ["***"]}
    assert envelope.payload == expected
    assert (await queue.get()).payload == expected
    assert (stream.replay(0) or [])[0].payload == expected


# --- binary frames: outside seq and replay, never merged, purgeable (specs/ws-chat-protocol) ---


def meta(seq: int, message_id: str, index: int) -> Envelope:
    return Envelope(
        type="tts.chunk.meta",
        seq=seq,
        conversation_id="c1",
        message_id=message_id,
        payload={"seq": index, "sentence_index": 0},
    )


async def test_publish_binary_goes_behind_the_last_envelope_without_seq_or_replay() -> None:
    stream = ConversationStream("c1")
    queue = OutboundQueue()
    stream.attach(queue)

    first = await stream.publish("tts.chunk.meta", {"seq": 0, "sentence_index": 0}, message_id="m")
    frame = await stream.publish_binary(b"\x01\x02", "m")
    second = await stream.publish("tts.end", {}, message_id="m")

    assert stream.last_seq == 2 and (first.seq, second.seq) == (1, 2)
    assert frame == BinaryFrame(b"\x01\x02", "m")
    assert [await queue.get() for _ in range(3)] == [first, frame, second]
    assert stream.replay(0) == [first, second]


async def test_full_queue_never_merges_or_drops_meta_and_binaries() -> None:
    queue = OutboundQueue(6)
    await queue.put(delta(1, "m", "a"))
    await queue.put(delta(2, "m", "b"))
    await queue.put(meta(3, "m", 0))
    await queue.put(BinaryFrame(b"\x00", "m"))
    await queue.put(meta(4, "m", 1))
    await queue.put(BinaryFrame(b"\x01", "m"))

    await queue.put(task(5, "task.result"))

    drained = [await queue.get() for _ in range(len(queue))]
    assert [getattr(item, "type", "bin") for item in drained] == [
        "assistant.delta",
        "tts.chunk.meta",
        "bin",
        "tts.chunk.meta",
        "bin",
        "task.result",
    ]
    assert drained[0].payload["text"] == "ab"


async def test_purge_removes_only_the_meta_and_binaries_of_one_message() -> None:
    queue = OutboundQueue()
    kept_meta, kept_frame = meta(1, "other", 0), BinaryFrame(b"\x09", "other")
    final = task(5, "assistant.final")
    for item in (meta(2, "m", 0), BinaryFrame(b"\x00", "m"), kept_meta, kept_frame, final):
        await queue.put(item)
    await queue.put(meta(6, "m", 1))
    await queue.put(BinaryFrame(b"\x01", "m"))

    removed = queue.purge("m")

    assert removed == 4
    assert [await queue.get() for _ in range(len(queue))] == [kept_meta, kept_frame, final]


async def test_drained_waits_until_the_consumer_has_finished_with_every_item() -> None:
    queue = OutboundQueue()
    await queue.put(task(1))
    await queue.put(task(2))

    drained = asyncio.ensure_future(queue.drained())
    await queue.get()
    queue.done()
    taken = await queue.get()
    await asyncio.sleep(0)
    assert not drained.done() and taken.seq == 2

    queue.done()
    await asyncio.wait_for(drained, 1)

    closed = OutboundQueue()
    await closed.put(task(3))
    closed.close()
    await asyncio.wait_for(closed.drained(), 1)


async def test_review05_finding_5_purge_wakes_a_blocked_publish_so_cancelled_gets_through() -> None:
    from tony.apps.web.tts_stream import ReplySink

    queue = OutboundQueue(3)
    stream = ConversationStream("c1")
    stream.attach(queue)
    for _ in range(3):
        await stream.publish_binary(b"\0\0", "m1")
    blocked = asyncio.ensure_future(stream.publish("assistant.delta", {"text": "hola"}))
    await asyncio.sleep(0.01)
    assert not blocked.done()

    await asyncio.wait_for(ReplySink(stream, "m1").cancelled(), 1)
    await asyncio.wait_for(blocked, 1)

    kinds = [item.type for item in queue._items]
    assert kinds == ["assistant.delta", "tts.cancelled"]


async def test_review05_finding_5_purging_everything_marks_the_queue_drained() -> None:
    queue = OutboundQueue(10)
    stream = ConversationStream("c1")
    stream.attach(queue)
    await stream.publish_binary(b"\0\0", "m1")
    waiting = asyncio.ensure_future(queue.drained())
    await asyncio.sleep(0.01)

    queue.purge("m1")

    await asyncio.wait_for(waiting, 0.5)
