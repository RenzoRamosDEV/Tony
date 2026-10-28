import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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

  send(text: string): void {
    this.sent.push(JSON.parse(text) as Record<string, unknown>);
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

function mount(routes: Record<string, unknown> = {}) {
  const calls: Call[] = [];
  render(
    <App
      socketFactory={(url) => new FakeWebSocket(url) as unknown as WebSocket}
      fetchImpl={fakeFetch({ "/api/settings": SETTINGS, ...routes }, calls)}
      storage={storage}
    />,
  );
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;
  return { ws, calls };
}

let storage: Storage;

describe("App", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    seq = 0;
    window.localStorage.clear();
    storage = window.localStorage;
  });

  afterEach(() => {
    FakeWebSocket.instances = [];
  });

  it("sends hello null on first load, stores the conversation and shows the empty state", async () => {
    const { ws, calls } = mount({ "/api/conversations/c-1/messages": [] });

    act(() => ws.open());
    expect(ws.sent[0]).toMatchObject({ type: "hello", payload: { conversation_id: null, last_seq: 0 } });
    act(() => ws.receive(helloOk()));

    await waitFor(() => expect(calls.some((c) => c.url === "/api/conversations/c-1/messages")).toBe(true));
    expect(storage.getItem("tony.conversation_id")).toBe("c-1");
    expect(screen.getByText("Escribe a Jarvis…")).toBeInTheDocument();
  });

  it("reopens the stored conversation and shows its history before accepting input", async () => {
    storage.setItem("tony.conversation_id", "c-1");
    const history = [
      { id: "m1", role: "user", content: "hola", reply_mode: null, created_at: "t" },
      { id: "m2", role: "assistant", content: "Hola, **señor**.", reply_mode: "text", created_at: "t" },
    ];
    const { ws } = mount({ "/api/conversations/c-1/messages": history });

    act(() => ws.open());
    expect(ws.sent[0]).toMatchObject({ payload: { conversation_id: "c-1" } });
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeDisabled();
    act(() => ws.receive(helloOk()));

    await waitFor(() => expect(screen.getByText("hola")).toBeInTheDocument());
    expect(screen.getByText("señor").tagName).toBe("STRONG");
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled();
  });

  it("sends user.text, shows the streamed answer and refreshes the settings after the final", async () => {
    const { ws, calls } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    await waitFor(() => expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled());

    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "hola{Enter}");
    expect(ws.sent.at(-1)).toMatchObject({ type: "user.text", payload: { text: "hola" } });
    act(() => ws.receive(env("user.accepted", { message_id: "u1", effective_mode: "text" }, { message_id: "u1" })));
    expect(screen.getByText("hola")).toBeInTheDocument();
    expect(screen.getByText("Jarvis está respondiendo…")).toBeInTheDocument();
    act(() => ws.receive(env("assistant.delta", { text: "Hola" }, { message_id: "a1" })));
    act(() => ws.receive(env("assistant.wait", { text: "Dame un momento." })));
    expect(screen.getByText("Dame un momento.")).toBeInTheDocument();
    const settingsCalls = calls.filter((c) => c.url === "/api/settings").length;

    act(() => ws.receive(env("assistant.final", { display_text: "Hola, Renzo.", speech_text: null, message_id: "a1" }, { message_id: "a1" })));

    expect(screen.getByText("Hola, Renzo.")).toBeInTheDocument();
    expect(screen.queryByText("Dame un momento.")).toBeNull();
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/settings").length).toBe(settingsCalls + 1));
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

  it("offers to cancel the active task until its result arrives", async () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    expect(screen.queryByRole("button", { name: "Cancelar tarea" })).toBeNull();
    act(() => ws.receive(env("task.queued", { objetivo: "x" }, { task_id: "t-9" })));
    act(() => ws.receive(env("task.running", {}, { task_id: "t-9" })));

    await userEvent.click(screen.getByRole("button", { name: "Cancelar tarea" }));

    expect(ws.sent.at(-1)).toMatchObject({ type: "cancel", payload: { task_id: "t-9" } });
    act(() => ws.receive(env("task.result", { result: { status: "cancelled" } }, { task_id: "t-9" })));
    expect(screen.queryByRole("button", { name: "Cancelar tarea" })).toBeNull();
  });

  it("shows server errors without losing the messages", () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    act(() => ws.receive(env("assistant.final", { display_text: "Hola.", speech_text: null, message_id: "a1" }, { message_id: "a1" })));

    act(() => ws.receive({ v: 1, type: "error", seq: 0, conversation_id: "c-1", payload: { code: "turn_in_progress", detail: "espera a que termine" } }));

    expect(screen.getByRole("alert")).toHaveTextContent("espera a que termine");
    expect(screen.getByText("Hola.")).toBeInTheDocument();
  });

  it("shows the disconnected banner and starts a new conversation on demand", async () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    expect(screen.getByRole("status")).toHaveTextContent("Desconectado, reintentando…");
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    expect(screen.queryByRole("status")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));

    expect(ws.sent.at(-1)).toMatchObject({ type: "hello", payload: { conversation_id: null } });
  });

  it("reloads the history on resync", async () => {
    const { ws, calls } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/messages")).length).toBe(1));

    act(() => ws.receive({ ...helloOk(), payload: { ...helloOk().payload, resync: true, last_seq: 900 } }));

    await waitFor(() => expect(calls.filter((c) => c.url.includes("/messages")).length).toBe(2));
  });
});
