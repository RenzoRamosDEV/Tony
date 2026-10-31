import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "./App";
import type { Envelope } from "./protocol/types";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

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
      this.sent.push(JSON.parse(data) as Record<string, unknown>);
    }
  }

  close(): void {
    this.readyState = 3;
  }
}

interface Call {
  url: string;
  init?: RequestInit;
}

function fakeFetch(routes: Record<string, unknown>, calls: Call[]) {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    calls.push({ url, init });
    const body = routes[url] ?? { error: "not_found", detail: url };
    const status = url in routes ? 200 : 404;
    return new Response(JSON.stringify(body), { status });
  };
}

const SETTINGS = { reply_mode: "auto", reply_mode_source: "yaml" };
let seq = 0;

function env(type: string, payload: Record<string, unknown>, extra: Partial<Envelope> = {}): Envelope {
  seq += 1;
  return { v: 1, type, seq, conversation_id: "c-1", payload, ...extra };
}

function helloOk(conversationId = "c-1"): Envelope {
  return {
    v: 1,
    type: "hello.ok",
    seq: 0,
    conversation_id: conversationId,
    payload: {
      conversation_id: conversationId,
      reply_mode: "auto",
      last_seq: 0,
      state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null },
    },
  };
}

const VOICE_OK = { available: true, reason: null, stt: "faster-whisper/small", tts: "kokoro/ef_dora" };
const HEALTH = { status: "ok", version: "x", front: "jarvis", worker: "viernes", mcp: [], voice: VOICE_OK };

function mount(routes: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  render(
    <App
      socketFactory={(url) => new FakeWebSocket(url) as unknown as WebSocket}
      fetchImpl={fakeFetch(
        {
          "/api/settings": SETTINGS,
          "/api/health": HEALTH,
          "/api/engines": { active: "claude_sdk", profiles: [{ name: "claude_sdk", type: "claude_sdk", model: null }] },
          ...routes,
        },
        calls,
      )}
      storage={storage}
    />,
  );
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;
  return { ws, calls };
}

let storage: Storage;

describe("App", () => {
  beforeEach(() => {
    storage = window.localStorage;
    storage.clear();
  });

  it("renders only the orb stage", () => {
    mount();

    expect(document.querySelector(".stage")).not.toBeNull();
    expect(document.querySelector(".hud")).toBeNull();
  });

  it("shows the confirmation card and sends confirm when accepted", async () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    act(() => ws.receive(env("task.queued", { objetivo: "x" }, { task_id: "t-9" })));
    act(() =>
      ws.receive(
        env("task.needs_confirmation", { confirmation_id: "a3f", tool: "filesystem.move_file", args: { a: 1 }, expires_in_s: 60 }, { task_id: "t-9" }),
      ),
    );
    expect(screen.getByText("filesystem.move_file")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(ws.sent.at(-1)).toMatchObject({ type: "confirm", payload: { confirmation_id: "a3f", approved: true } });
    act(() => ws.receive(env("task.confirmed", { confirmation_id: "a3f", approved: true }, { task_id: "t-9" })));
    expect(screen.queryByRole("button", { name: "Confirmar" })).toBeNull();
  });
});
