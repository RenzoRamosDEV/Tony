import { act, render, screen, waitFor, within } from "@testing-library/react";
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

  sentBinary: ArrayBuffer[] = [];
  binaryType = "blob";

  send(data: string | ArrayBuffer): void {
    if (typeof data === "string") {
      this.sent.push(JSON.parse(data) as Record<string, unknown>);
    } else {
      this.sentBinary.push(data);
    }
  }

  receiveBinary(buffer: ArrayBuffer): void {
    (this.onmessage as unknown as (event: { data: ArrayBuffer }) => void)?.({ data: buffer });
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

function mount(routes: Record<string, unknown> = {}, audio?: FakeAudio) {
  const calls: Call[] = [];
  render(
    <App
      socketFactory={(url) => new FakeWebSocket(url) as unknown as WebSocket}
      fetchImpl={fakeFetch({ "/api/settings": SETTINGS, "/api/health": HEALTH, ...routes }, calls)}
      storage={storage}
      {...(audio ? { micDeps: audio.micDeps, audioContextFactory: () => audio.output as unknown as AudioContext } : {})}
    />,
  );
  const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]!;
  return { ws, calls };
}

let storage: Storage;

class FakeSource {
  started: number | null = null;
  stopped = false;
  onended: (() => void) | null = null;
  buffer: unknown = null;
  connect(): void {}
  start(when: number): void {
    this.started = when;
  }
  stop(): void {
    this.stopped = true;
  }
}

class FakeOutputContext {
  currentTime = 0;
  sampleRate = 24000;
  destination = {};
  state = "running";
  sources: FakeSource[] = [];
  createBuffer(_c: number, length: number, rate: number) {
    const data = new Float32Array(length);
    return { duration: length / rate, getChannelData: () => data };
  }
  outputLevel = 0;
  createAnalyser() {
    return {
      fftSize: 2048,
      smoothingTimeConstant: 0.8,
      connect: () => undefined,
      getFloatTimeDomainData: (out: Float32Array) => out.fill(this.outputLevel),
    };
  }
  createBufferSource() {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
  async resume(): Promise<void> {}
  async close(): Promise<void> {}
  finishAll(): void {
    for (const source of this.sources) {
      source.onended?.();
    }
  }
}

class FakeAudio {
  requests: MediaStreamConstraints[] = [];
  tracks = [{ stopped: false, stop() { this.stopped = true; } }];
  port = { onmessage: null as ((event: { data: Float32Array }) => void) | null };
  output = new FakeOutputContext();
  permission: "granted" | "denied" = "granted";
  micDeps = {
    getUserMedia: async (constraints: MediaStreamConstraints) => {
      this.requests.push(constraints);
      if (this.permission === "denied") {
        throw new DOMException("denied", "NotAllowedError");
      }
      return { getTracks: () => this.tracks } as unknown as MediaStream;
    },
    createContext: () =>
      ({
        audioWorklet: { addModule: async () => undefined },
        createMediaStreamSource: () => ({ connect: () => undefined }),
        close: async () => undefined,
      }) as unknown as AudioContext,
    createNode: () => ({ port: this.port, connect: () => undefined, disconnect: () => undefined }) as unknown as AudioWorkletNode,
    workletUrl: "worklet.js",
  };

  speak(value = 0.5): void {
    this.port.onmessage?.({ data: new Float32Array(480).fill(value) });
  }
}

function pcm(ms: number): ArrayBuffer {
  return new Int16Array((24000 * ms) / 1000).fill(1000).buffer;
}

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

describe("App (review of change 04)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    seq = 0;
    window.localStorage.clear();
    storage = window.localStorage;
  });

  it("finding 14: blocks a second send until the first is acknowledged by its client_id", async () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    await waitFor(() => expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled());

    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "A{Enter}");

    const sent = ws.sent.at(-1) as { type: string; payload: { text: string; client_id: string } };
    expect(sent.type).toBe("user.text");
    expect(typeof sent.payload.client_id).toBe("string");
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeDisabled();
    act(() => ws.receive(env("user.accepted", { message_id: "u1", effective_mode: "text", client_id: sent.payload.client_id }, { message_id: "u1" })));
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("Jarvis está respondiendo…")).toBeInTheDocument();
    act(() => ws.receive(env("assistant.final", { display_text: "Hecho.", speech_text: null, message_id: "a1" }, { message_id: "a1" })));
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled();
  });

  it("finding 14: keeps the draft when the socket is not open", async () => {
    const { ws } = mount({ "/api/conversations/c-1/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    await waitFor(() => expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled());
    ws.readyState = 3;

    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "borrador{Enter}");

    expect(ws.sent.some((m) => m.type === "user.text")).toBe(false);
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toHaveValue("borrador");
  });

  it("finding 9: a new conversation reloads its own history and empties the chat", async () => {
    const { ws, calls } = mount({ "/api/conversations/c-1/messages": [], "/api/conversations/c-2/messages": [] });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));
    act(() => ws.receive(env("assistant.final", { display_text: "Primera.", speech_text: null, message_id: "a1" }, { message_id: "a1" })));
    await waitFor(() => expect(screen.getByText("Primera.")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Nueva conversación" }));
    act(() => ws.receive(helloOk("c-2")));

    await waitFor(() => expect(calls.some((c) => c.url === "/api/conversations/c-2/messages")).toBe(true));
    expect(screen.queryByText("Primera.")).toBeNull();
    expect(storage.getItem("tony.conversation_id")).toBe("c-2");
  });
});


describe("App (voice)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    seq = 0;
    window.localStorage.clear();
    storage = window.localStorage;
  });

  async function connected(audio: FakeAudio, routes: Record<string, unknown> = {}) {
    const mounted = mount({ "/api/conversations/c-1/messages": [], ...routes }, audio);
    act(() => mounted.ws.open());
    act(() => mounted.ws.receive(helloOk()));
    await waitFor(() => expect(mounted.calls.some((c) => c.url === "/api/health")).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "Activar micrófono" })).toBeEnabled());
    return mounted;
  }

  async function listening(audio: FakeAudio) {
    const mounted = await connected(audio);
    await userEvent.click(screen.getByRole("button", { name: "Activar micrófono" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Desactivar micrófono" })).toBeInTheDocument());
    return mounted;
  }

  it("disables the microphone with the install hint when the server has no voice", async () => {
    const { ws } = mount({
      "/api/conversations/c-1/messages": [],
      "/api/health": { ...HEALTH, voice: { ...VOICE_OK, available: false, reason: "extra tony[voice] no instalado" } },
    });
    act(() => ws.open());
    act(() => ws.receive(helloOk()));

    await waitFor(() => expect(screen.getByRole("button", { name: "Activar micrófono" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Activar micrófono" })).toHaveAttribute("title", expect.stringContaining("uv sync --extra voice"));
  });

  it("the microphone sends audio.start and streams the worklet frames as binary", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    expect(audio.requests[0]).toMatchObject({ audio: { channelCount: 1, echoCancellation: true } });
    expect(ws.sent.at(-1)).toMatchObject({ type: "audio.start", payload: { sample_rate: 16000, channels: 1, format: "f32" } });
    expect(screen.getByRole("status")).toHaveTextContent("Escuchando…");

    act(() => audio.speak());
    act(() => audio.speak());

    expect(ws.sentBinary).toHaveLength(2);
    expect(ws.sentBinary[0]!.byteLength).toBe(480 * 4);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "100");

    await userEvent.click(screen.getByRole("button", { name: "Desactivar micrófono" }));
    expect(ws.sent.at(-1)).toMatchObject({ type: "audio.end" });
    expect(audio.tracks[0]!.stopped).toBe(true);
  });

  it("mutes the capture from tts.start until the playback drains after tts.end", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));
    expect(screen.getByRole("status")).toHaveTextContent("Hablando…");
    act(() => audio.speak());
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 1, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));
    act(() => audio.speak());

    expect(ws.sentBinary).toHaveLength(0);
    expect(audio.output.sources.map((s) => s.started)).toEqual([0, 0.5]);
    act(() => ws.receive(env("tts.end", { message_id: "a-1" }, { message_id: "a-1" })));
    expect(screen.getByRole("status")).toHaveTextContent("Hablando…");
    act(() => audio.speak());
    expect(ws.sentBinary).toHaveLength(0);

    act(() => audio.output.finishAll());

    expect(screen.getByRole("status")).toHaveTextContent("Escuchando…");
    act(() => audio.speak());
    expect(ws.sentBinary).toHaveLength(1);
  });

  it("a binary frame without a pending meta is discarded", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);
    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));

    act(() => ws.receiveBinary(pcm(100)));

    expect(audio.output.sources).toHaveLength(0);
  });

  it("tts.cancelled stops the playback at once", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);
    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));

    act(() => ws.receive(env("tts.cancelled", { message_id: "a-1" }, { message_id: "a-1" })));

    expect(audio.output.sources[0]!.stopped).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("Escuchando…");
    act(() => audio.speak());
    expect(ws.sentBinary).toHaveLength(1);
  });

  it("'Detener audio' stops the playback and sends cancel for the spoken message", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);
    act(() => ws.receive(env("tts.start", { message_id: "a-2" }, { message_id: "a-2" })));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-2" })));
    act(() => ws.receiveBinary(pcm(500)));

    await userEvent.click(screen.getByRole("button", { name: "Detener audio" }));

    expect(audio.output.sources[0]!.stopped).toBe(true);
    expect(ws.sent.at(-1)).toMatchObject({ type: "cancel", payload: { message_id: "a-2" } });
    act(() => ws.receive(env("tts.cancelled", { message_id: "a-2" }, { message_id: "a-2" })));
    expect(screen.queryByRole("button", { name: "Detener audio" })).toBeNull();
  });

  it("shows the transcription as a voice bubble and the full answer rendered", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => ws.receive(env("stt.final", { text: "¿qué hora es?", message_id: "m-1" }, { message_id: "m-1" })));
    act(() => ws.receive(env("user.accepted", { message_id: "m-1", effective_mode: "voice", client_id: null }, { message_id: "m-1" })));
    act(() =>
      ws.receive(
        env("assistant.final", { display_text: "| a | b |\n|---|---|\n| 1 | 2 |", speech_text: "Dos filas.", message_id: "a-1" }, { message_id: "a-1" }),
      ),
    );

    const bubble = screen.getByRole("article", { name: "Mensaje tuyo por voz" });
    expect(bubble).toHaveTextContent("¿qué hora es?");
    expect(bubble).toHaveTextContent("voice");
    expect(screen.getByTitle("Transcrito del micrófono")).toBeInTheDocument();
    expect(document.querySelector("table")).not.toBeNull();
  });

  it("a denied permission shows a Spanish notice and never sends audio.start", async () => {
    const audio = new FakeAudio();
    audio.permission = "denied";
    const { ws } = await connected(audio);

    await userEvent.click(screen.getByRole("button", { name: "Activar micrófono" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("micrófono"));
    expect(ws.sent.some((m) => m.type === "audio.start")).toBe(false);
    expect(screen.getByRole("button", { name: "Activar micrófono" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("App (review of change 05)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    seq = 0;
    window.localStorage.clear();
    storage = window.localStorage;
  });

  async function listening(audio: FakeAudio) {
    const mounted = mount({ "/api/conversations/c-1/messages": [], "/api/conversations/c-2/messages": [] }, audio);
    act(() => mounted.ws.open());
    act(() => mounted.ws.receive(helloOk()));
    await waitFor(() => expect(screen.getByRole("button", { name: "Activar micrófono" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Activar micrófono" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Desactivar micrófono" })).toBeInTheDocument());
    return mounted;
  }

  it("finding 8: meta and binary delivered before any render are enqueued with their sequence", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => {
      ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" }));
      ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" }));
      ws.receiveBinary(pcm(500));
      ws.receive(env("tts.chunk.meta", { seq: 1, sentence_index: 0 }, { message_id: "a-1" }));
      ws.receiveBinary(pcm(250));
    });

    expect(audio.output.sources.map((s) => s.started)).toEqual([0, 0.5]);
  });

  it("finding 9: a server rejection of audio.start really stops the capture", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => ws.receive({ v: 1, type: "error", seq: 0, conversation_id: "c-1", payload: { code: "unsupported_audio", detail: "formato" } }));

    expect(audio.tracks[0]!.stopped).toBe(true);
    expect(screen.getByRole("button", { name: "Activar micrófono" })).toHaveAttribute("aria-pressed", "false");
    act(() => audio.speak());
    expect(ws.sentBinary).toHaveLength(0);
  });

  it("finding 10: a disconnect stops the capture and requires enabling the microphone again", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => {
      ws.readyState = 3;
      ws.onclose?.();
    });

    expect(audio.tracks[0]!.stopped).toBe(true);
    expect(screen.getByRole("button", { name: "Activar micrófono" })).toHaveAttribute("aria-pressed", "false");
  });

  it("finding 10: a new conversation stops the capture", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);

    act(() => ws.receive(helloOk("c-2")));

    expect(audio.tracks[0]!.stopped).toBe(true);
    act(() => audio.speak());
    expect(ws.sentBinary).toHaveLength(0);
  });

  it("finding 11: an accepted new turn stops audio still playing after tts.end", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);
    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));
    act(() => ws.receive(env("tts.end", { message_id: "a-1" }, { message_id: "a-1" })));

    act(() => ws.receive(env("user.accepted", { message_id: "m-2", effective_mode: "voice", client_id: null }, { message_id: "m-2" })));

    expect(audio.output.sources[0]!.stopped).toBe(true);
  });

  it("finding 11: stopping audio after tts.end stops locally without a stale cancel", async () => {
    const audio = new FakeAudio();
    const { ws } = await listening(audio);
    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));
    act(() => ws.receive(env("tts.end", { message_id: "a-1" }, { message_id: "a-1" })));

    await userEvent.click(screen.getByRole("button", { name: "Detener audio" }));

    expect(audio.output.sources[0]!.stopped).toBe(true);
    expect(ws.sent.some((m) => m.type === "cancel")).toBe(false);
  });
});

describe("App (orb and HUD)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    seq = 0;
    window.localStorage.clear();
    storage = window.localStorage;
  });

  function orbState(): string | null {
    return document.querySelector(".stage")?.getAttribute("data-orb-state") ?? null;
  }

  async function ready(audio?: FakeAudio, routes: Record<string, unknown> = {}) {
    const mounted = mount({ "/api/conversations/c-1/messages": [], ...routes }, audio);
    act(() => mounted.ws.open());
    act(() => mounted.ws.receive(helloOk()));
    await waitFor(() => expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeEnabled());
    return mounted;
  }

  it("shows the decorative orb, as a CSS orb when there is no WebGL", async () => {
    await ready();

    expect(document.querySelector(".stage")).toHaveAttribute("aria-hidden", "true");
    expect(document.querySelector(".orb-fallback")).not.toBeNull();
    expect(orbState()).toBe("idle");
  });

  it("thinks from user.accepted until the final answer", async () => {
    const { ws } = await ready();
    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "hola{Enter}");

    act(() => ws.receive(env("user.accepted", { message_id: "u1", effective_mode: "text" }, { message_id: "u1" })));
    expect(orbState()).toBe("thinking");

    act(() => ws.receive(env("assistant.final", { display_text: "Hola.", speech_text: null, message_id: "a1" }, { message_id: "a1" })));
    expect(orbState()).toBe("idle");
  });

  it("thinks while a task runs without a turn", async () => {
    const { ws } = await ready();

    act(() => ws.receive(env("task.queued", { objetivo: "x" }, { task_id: "t-9" })));

    expect(orbState()).toBe("thinking");
  });

  it("listens with the microphone on and speaks while the reply plays", async () => {
    const audio = new FakeAudio();
    const { ws } = await ready(audio, { "/api/health": HEALTH });
    await waitFor(() => expect(screen.getByRole("button", { name: "Activar micrófono" })).toBeEnabled());

    await userEvent.click(screen.getByRole("button", { name: "Activar micrófono" }));
    await waitFor(() => expect(orbState()).toBe("listening"));

    act(() => ws.receive(env("tts.start", { message_id: "a-1" }, { message_id: "a-1" })));
    act(() => ws.receive(env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-1" })));
    act(() => ws.receiveBinary(pcm(500)));
    act(() => ws.receive(env("tts.end", { message_id: "a-1" }, { message_id: "a-1" })));
    expect(orbState()).toBe("speaking");

    act(() => audio.output.finishAll());
    expect(orbState()).toBe("listening");
  });

  it("puts the controls in the bottom HUD bar", async () => {
    await ready();
    const bar = screen.getByRole("group", { name: "Controles de Jarvis" });

    expect(bar).toContainElement(screen.getByPlaceholderText("Escribe a Jarvis…"));
    expect(bar).toContainElement(screen.getByRole("button", { name: "Activar micrófono" }));
    expect(bar).toContainElement(screen.getByRole("radiogroup", { name: "Modo de respuesta" }));
  });

  it("cancels from the HUD bar", async () => {
    const { ws } = await ready();
    act(() => ws.receive(env("task.queued", { objetivo: "x" }, { task_id: "t-9" })));
    act(() => ws.receive(env("task.running", {}, { task_id: "t-9" })));
    const bar = screen.getByRole("group", { name: "Controles de Jarvis" });

    await userEvent.click(within(bar).getByRole("button", { name: /Cancelar tarea/ }));

    expect(ws.sent.at(-1)).toMatchObject({ type: "cancel", payload: { task_id: "t-9" } });
  });

  it("shows the last exchange as subtitles and the whole history in the transcript", async () => {
    storage.setItem("tony.conversation_id", "c-1");
    const history = [
      { id: "m1", role: "user", content: "primera", reply_mode: null, created_at: "t" },
      { id: "m2", role: "assistant", content: "respuesta uno", reply_mode: "text", created_at: "t" },
      { id: "m3", role: "user", content: "segunda", reply_mode: null, created_at: "t" },
      { id: "m4", role: "assistant", content: "respuesta dos", reply_mode: "text", created_at: "t" },
    ];
    await ready(undefined, { "/api/conversations/c-1/messages": history });
    await waitFor(() => expect(screen.getByText("respuesta dos")).toBeInTheDocument());
    const subtitles = screen.getByRole("region", { name: "Subtítulos" });

    expect(subtitles).toHaveTextContent("segunda");
    expect(subtitles).not.toHaveTextContent("primera");

    await userEvent.click(screen.getByRole("button", { name: "Mostrar transcripción" }));

    expect(screen.getByRole("region", { name: "Transcripción" }).querySelectorAll("article")).toHaveLength(4);
  });

  it("centres the confirmation card and focuses Rechazar", async () => {
    const { ws } = await ready();
    act(() => ws.receive(env("task.queued", { objetivo: "x" }, { task_id: "t-9" })));

    act(() =>
      ws.receive(
        env("task.needs_confirmation", { confirmation_id: "a3f", tool: "filesystem.move_file", args: {}, expires_in_s: 60 }, { task_id: "t-9" }),
      ),
    );

    expect(screen.getByRole("button", { name: "Rechazar" })).toHaveFocus();
  });
});
