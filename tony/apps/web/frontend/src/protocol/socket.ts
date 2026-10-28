import type { ClientMessage, Envelope } from "./types";

export const RECONNECT_DELAY_MS = 2000;

export interface ChatSocketOptions {
  url: string;
  onEnvelope: (envelope: Envelope) => void;
  onStatus: (connected: boolean) => void;
  conversationId: () => string | null;
  lastSeq: () => number;
  factory?: (url: string) => WebSocket;
}

export function defaultSocketUrl(location: Location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/chat`;
}

/** Keeps one WebSocket open, reconnecting every two seconds and greeting with `hello`. */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  private seq = 0;

  constructor(private readonly options: ChatSocketOptions) {}

  connect(): void {
    if (this.closed) {
      return;
    }
    const factory = this.options.factory ?? ((url: string) => new WebSocket(url));
    const ws = factory(this.options.url);
    this.ws = ws;
    ws.onopen = () => {
      this.options.onStatus(true);
      this.hello(this.options.conversationId());
    };
    ws.onmessage = (event) => this.receive(String(event.data));
    ws.onerror = () => undefined;
    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null;
        this.options.onStatus(false);
        this.scheduleReconnect();
      }
    };
  }

  send(message: ClientMessage): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    this.seq += 1;
    ws.send(
      JSON.stringify({
        v: 1,
        type: message.type,
        seq: this.seq,
        conversation_id: this.options.conversationId(),
        payload: message.payload,
      }),
    );
  }

  newConversation(): void {
    this.hello(null);
  }

  close(): void {
    this.closed = true;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  private hello(conversationId: string | null): void {
    this.send({ type: "hello", payload: { conversation_id: conversationId, last_seq: this.options.lastSeq() } });
  }

  private receive(data: string): void {
    let envelope: Envelope;
    try {
      envelope = JSON.parse(data) as Envelope;
    } catch {
      return;
    }
    if (envelope.type === "error" && envelope.payload.code === "unknown_conversation") {
      this.hello(null);
    }
    this.options.onEnvelope(envelope);
  }

  private scheduleReconnect(): void {
    if (this.closed || this.timer !== null) {
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, RECONNECT_DELAY_MS);
  }
}
