import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatSocket, RECONNECT_DELAY_MS } from "./socket";
import type { Envelope } from "./types";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  sentBinary: ArrayBuffer[] = [];
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(envelope: Envelope): void {
    this.onmessage?.({ data: JSON.stringify(envelope) });
  }

  send(data: string | ArrayBuffer): void {
    if (typeof data === "string") {
      this.sent.push(data);
    } else {
      this.sentBinary.push(data);
    }
  }

  close(): void {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.();
  }

  serverClose(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  sentJson(): unknown[] {
    return this.sent.map((s) => JSON.parse(s));
  }
}

function hello(conversationId: string | null, lastSeq: number) {
  return expect.objectContaining({
    v: 1,
    type: "hello",
    payload: { conversation_id: conversationId, last_seq: lastSeq },
  });
}

describe("ChatSocket", () => {
  let received: Envelope[];
  let socket: ChatSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    received = [];
    socket = new ChatSocket({
      url: "ws://test/ws/chat",
      factory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      onEnvelope: (e) => received.push(e),
      onStatus: () => undefined,
      conversationId: () => "c-1",
      lastSeq: () => received.length,
    });
  });

  afterEach(() => {
    socket.close();
    vi.useRealTimers();
  });

  it("sends hello with the conversation and last_seq when the socket opens", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    expect(ws.sent).toEqual([]);

    ws.open();

    expect(ws.url).toBe("ws://test/ws/chat");
    expect(ws.sentJson()).toEqual([hello("c-1", 0)]);
  });

  it("delivers parsed envelopes and ignores malformed frames", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();
    ws.receive({ v: 1, type: "assistant.wait", seq: 1, conversation_id: "c-1", payload: { text: "x" } });
    ws.onmessage?.({ data: "{not json" });

    expect(received.map((e) => e.type)).toEqual(["assistant.wait"]);
  });

  it("reconnects two seconds after a close and resends hello with the last seq", () => {
    const statuses: boolean[] = [];
    socket = new ChatSocket({
      url: "ws://test/ws/chat",
      factory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      onEnvelope: (e) => received.push(e),
      onStatus: (connected) => statuses.push(connected),
      conversationId: () => "c-1",
      lastSeq: () => 18,
    });
    socket.connect();
    const first = FakeWebSocket.instances[0]!;
    first.open();
    first.serverClose();
    expect(statuses).toEqual([true, false]);

    vi.advanceTimersByTime(RECONNECT_DELAY_MS - 1);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    const second = FakeWebSocket.instances[1]!;
    second.open();

    expect(second.sentJson()).toEqual([hello("c-1", 18)]);
    expect(statuses).toEqual([true, false, true]);
  });

  it("drops messages sent while disconnected without throwing", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;

    expect(() => socket.send({ type: "user.text", payload: { text: "hola" } })).not.toThrow();
    ws.open();
    socket.send({ type: "user.text", payload: { text: "hola" } });

    expect(ws.sentJson().map((m) => (m as { type: string }).type)).toEqual(["hello", "user.text"]);
  });

  it("answers unknown_conversation with a fresh hello", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();

    ws.receive({ v: 1, type: "error", seq: 0, conversation_id: null, payload: { code: "unknown_conversation", detail: "no" } });

    expect(ws.sentJson()).toEqual([hello("c-1", 0), hello(null, 0)]);
  });

  it("hello(null) starts a new conversation on demand", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();

    socket.newConversation();

    expect(ws.sentJson()[1]).toEqual(hello(null, 0));
  });

  it("close stops reconnecting", () => {
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();

    socket.close();
    vi.advanceTimersByTime(RECONNECT_DELAY_MS * 2);

    expect(ws.closed).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe("ChatSocket (review of change 04)", () => {
  it("finding 14: send reports whether the frame was transmitted", () => {
    const socket = new ChatSocket({
      url: "ws://x/ws/chat",
      onEnvelope: () => undefined,
      onStatus: () => undefined,
      conversationId: () => null,
      lastSeq: () => 0,
      factory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
    });
    socket.connect();
    const ws = FakeWebSocket.instances.at(-1)!;

    expect(socket.send({ type: "user.text", payload: { text: "antes" } })).toBe(false);
    ws.open();
    expect(socket.send({ type: "user.text", payload: { text: "ahora" } })).toBe(true);
    socket.close();
  });
});

describe("ChatSocket binary frames", () => {
  it("sends ArrayBuffers as binary frames only while open", () => {
    FakeWebSocket.instances = [];
    const binaries: ArrayBuffer[] = [];
    const socket = new ChatSocket({
      url: "ws://test/ws/chat",
      factory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      onEnvelope: () => undefined,
      onStatus: () => undefined,
      onAudio: (_meta, buffer) => binaries.push(buffer),
      conversationId: () => "c-1",
      lastSeq: () => 0,
    });
    const frame = new Float32Array(480).buffer;
    expect(socket.sendBinary(frame)).toBe(false);

    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();
    expect(socket.sendBinary(frame)).toBe(true);
    expect(ws.binaryType).toBe("arraybuffer");
    expect(ws.sentBinary).toEqual([frame]);

    const incoming = new Int16Array([1, 2, 3]).buffer;
    ws.receive({ v: 1, type: "tts.chunk.meta", seq: 1, conversation_id: "c-1", message_id: "a-1", payload: { seq: 0, sentence_index: 0 } });
    ws.onmessage?.({ data: incoming } as unknown as { data: string });
    expect(binaries).toEqual([incoming]);
    socket.close();
  });
});

describe("ChatSocket (review of change 05)", () => {
  it("finding 8: pairs each tts.chunk.meta with the next binary frame synchronously", () => {
    FakeWebSocket.instances = [];
    const audio: [string, number, number][] = [];
    const socket = new ChatSocket({
      url: "ws://test/ws/chat",
      factory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      onEnvelope: () => undefined,
      onStatus: () => undefined,
      onAudio: (meta, buffer) => audio.push([meta.messageId, meta.seq, buffer.byteLength]),
      conversationId: () => "c-1",
      lastSeq: () => 0,
    });
    socket.connect();
    const ws = FakeWebSocket.instances[0]!;
    ws.open();
    const binary = (bytes: number) => ws.onmessage?.({ data: new ArrayBuffer(bytes) } as unknown as { data: string });
    const meta = (seq: number) =>
      ws.receive({ v: 1, type: "tts.chunk.meta", seq: seq + 1, conversation_id: "c-1", message_id: "a-1", payload: { seq, sentence_index: 0 } });

    binary(2);
    meta(0);
    binary(4);
    binary(6);
    meta(1);
    binary(8);

    expect(audio).toEqual([
      ["a-1", 0, 4],
      ["a-1", 1, 8],
    ]);
    socket.close();
  });
});
