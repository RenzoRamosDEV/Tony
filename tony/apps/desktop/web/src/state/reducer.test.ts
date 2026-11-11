import { describe, expect, it } from "vitest";

import type { AuditRow, CoreEvent, ToolCallEvent } from "../bridge/types";
import { initialState, micView, reduce, type UiAction, type UiState, visibleAudit } from "./reducer";

const TS = "2026-11-01T10:00:00+00:00";
const NOW = 1_000_000;

function apply(...items: (CoreEvent | UiAction)[]): UiState {
  return items.reduce<UiState>(
    (state, item) => reduce(state, "kind" in item ? item : { kind: "event", event: item, now: NOW }),
    initialState(),
  );
}

const token = (agent: string, text: string): CoreEvent => ({ type: "token", ts: TS, agent, text });
const turnStarted = (writes: boolean): CoreEvent => ({
  type: "turn_started", ts: TS, agent: "jarvis", origin: "text", reply_mode: "auto", speaks: !writes, writes,
});
const turnResult = (text: string): CoreEvent => ({
  type: "result", ts: TS, scope: "turn", agent: "jarvis", text, reply_mode: "auto",
});
const taskStarted = (taskId = "t1", agent = "viernes"): CoreEvent => ({
  type: "task_started", ts: TS, task_id: taskId, agent, objetivo: "leer notas",
});
const toolCall = (taskId = "t1", over: Partial<ToolCallEvent> = {}): ToolCallEvent => ({
  type: "tool_call", ts: TS, task_id: taskId, agent: "viernes", tool: "filesystem.read_file",
  args_preview: "{}", verdict: "allow", rule: "r/allow", user_decision: null, ...over,
});
const taskResult = (taskId = "t1"): CoreEvent => ({
  type: "result", ts: TS, scope: "task", task_id: taskId, agent: "viernes", outcome: "ok",
  result: { resumen: "hecho" }, input_tokens: 100, output_tokens: 20, elapsed_ms: 1500,
});
const confirmation = (taskId = "t1", allowAlways = true): CoreEvent => ({
  type: "needs_confirmation", ts: TS, task_id: taskId, tool: "filesystem.delete_file",
  args_preview: '{"path": "a.md"}', question: "¿Borrar a.md?", allow_always: allowAlways,
});
const auth = (state: "locked" | "unlocked", reason: string, retry = 0): CoreEvent =>
  ({ type: "auth", ts: TS, state, reason, retry_in_s: retry }) as CoreEvent;
const voice = (state: string, reason: string | null = null): CoreEvent =>
  ({ type: "voice_state", ts: TS, state, reason }) as CoreEvent;
const error = (source: string, message = "fallo"): CoreEvent => ({ type: "error", ts: TS, source, message });

describe("audio devices", () => {
  it("audio_devices event updates the audioDevices slice", () => {
    const state = reduce(initialState(), {
      kind: "event",
      now: Date.now(),
      event: {
        type: "audio_devices", ts: "",
        input: [{ name: "Mic A", is_default: true }], output: [],
        selected_input: "Mic A", selected_output: null,
        input_fallback_warning: null, output_fallback_warning: null,
      },
    });
    expect(state.audioDevices.selectedInput).toBe("Mic A");
    expect(state.audioDevices.input).toEqual([{ name: "Mic A", is_default: true }]);
  });
});

describe("chat", () => {
  it("streams tokens into one bubble per agent with its label and colour", () => {
    const state = apply(token("jarvis", "Hola"), token("jarvis", ", señor"), token("viernes", "Leo"));

    expect(state.messages.map((m) => [m.label, m.colour, m.text])).toEqual([
      ["Jarvis", "#2F6FED", "Hola, señor"],
      ["Viernes", "#2E9E5B", "Leo"],
    ]);
  });

  it("uses Edith's colour and a neutral colour for unknown agents", () => {
    const state = apply(token("edith", "x"), token("otro", "y"));

    expect(state.messages.map((m) => m.colour)).toEqual(["#E0A100", "#6B7280"]);
  });

  it("starts a new bubble after the turn result closes the streamed one", () => {
    const state = apply(token("jarvis", "Uno"), turnResult("Uno"), token("jarvis", "Dos"));

    expect(state.messages.map((m) => m.text)).toEqual(["Uno", "Dos"]);
  });

  it("a non-writing turn hides its tokens and adds the full result", () => {
    const state = apply(turnStarted(false), token("jarvis", "Ho"), token("jarvis", "la"), turnResult("Hola."));

    expect(state.messages.map((m) => [m.agent, m.text])).toEqual([["jarvis", "Hola."]]);
  });

  it("a writing turn shows its tokens and does not repeat the result", () => {
    const state = apply(turnStarted(true), token("jarvis", "Hola."), turnResult("Hola."));

    expect(state.messages.map((m) => m.text)).toEqual(["Hola."]);
  });

  it("an empty result of a non-writing turn adds nothing", () => {
    expect(apply(turnStarted(false), turnResult("")).messages).toEqual([]);
  });

  it("the next turn writes again after a non-writing one ended", () => {
    const state = apply(turnStarted(false), turnResult("A."), token("jarvis", "B"));

    expect(state.messages.map((m) => m.text)).toEqual(["A.", "B"]);
  });

  it("a transcript is a user bubble labelled «Tú (voz)»", () => {
    const [message] = apply({ type: "transcript", ts: TS, text: "¿Qué hora es?" }).messages;

    expect([message?.kind, message?.label, message?.text]).toEqual(["user", "Tú (voz)", "¿Qué hora es?"]);
  });

  it("a sent message is a user bubble labelled «Tú»", () => {
    const [message] = apply({ kind: "sent", text: "Hola" }).messages;

    expect([message?.kind, message?.label, message?.text]).toEqual(["user", "Tú", "Hola"]);
  });

  it("progress is a bubble of its agent", () => {
    const [message] = apply({ type: "progress", ts: TS, agent: "jarvis", text: "Un momento." }).messages;

    expect([message?.agent, message?.text]).toEqual(["jarvis", "Un momento."]);
  });

  it("an error is a system line naming its source", () => {
    const [message] = apply(error("listen", "sin micrófono")).messages;

    expect([message?.kind, message?.text]).toEqual(["system", "Error (listen): sin micrófono"]);
  });

  it("a front error lets the next tokens be written", () => {
    const state = apply(turnStarted(false), error("front"), token("jarvis", "x"));

    expect(state.messages.map((m) => m.text)).toEqual(["Error (front): fallo", "x"]);
  });

  it("messages get unique ids", () => {
    const ids = apply({ kind: "sent", text: "a" }, { kind: "sent", text: "b" }).messages.map((m) => m.id);

    expect(new Set(ids).size).toBe(2);
  });
});

describe("reply mode", () => {
  it("starts at auto and follows reply_mode", () => {
    expect(initialState().replyMode).toBe("auto");
    expect(apply({ type: "reply_mode", ts: TS, mode: "both" }).replyMode).toBe("both");
  });
});

describe("microphone", () => {
  it.each([
    ["loading", null, false, "Micrófono", "Cargando los modelos de voz…"],
    ["ready", null, true, "Micrófono", "Pulse para decir una frase"],
    ["listening", null, true, "Escuchando…", "Escuchando: pulse para parar"],
    ["unavailable", "sin extra voice", false, "Micrófono", "Voz no disponible: sin extra voice"],
  ])("%s", (name, reason, enabled, label, tooltip) => {
    expect(micView(apply(voice(name, reason)).voice)).toEqual({ enabled, label, tooltip });
  });

  it("starts loading", () => {
    expect(initialState().voice).toEqual({ state: "loading", reason: null });
  });
});

describe("activity", () => {
  it("lists a started task as running", () => {
    const [task] = apply(taskStarted()).tasks;

    expect([task?.label, task?.summary]).toEqual(["viernes: leer notas", "en curso"]);
  });

  it("adds tool calls with verdict and user decision", () => {
    const state = apply(
      taskStarted(),
      toolCall("t1"),
      toolCall("t1", { tool: "filesystem.delete_file", verdict: "confirm", user_decision: "allow" }),
    );

    expect(state.tasks[0]?.calls.map((c) => c.label)).toEqual([
      "filesystem.read_file — allow",
      "filesystem.delete_file — confirm (allow)",
    ]);
  });

  it("groups subagent calls under <agent>/<subagent>", () => {
    const state = apply(
      taskStarted(),
      toolCall("t1", { agent: "viernes/lector" }),
      toolCall("t1", { agent: "viernes/lector", tool: "b" }),
      toolCall("t1", { agent: "viernes/otro", tool: "c" }),
    );
    const task = state.tasks[0];

    expect(task?.calls).toEqual([]);
    expect(task?.subagents.map((s) => [s.name, s.calls.map((c) => c.tool)])).toEqual([
      ["lector", ["filesystem.read_file", "b"]],
      ["otro", ["c"]],
    ]);
  });

  it("ignores tool calls of unknown tasks", () => {
    expect(apply(toolCall("nope")).tasks).toEqual([]);
  });

  it("summarises a finished task with tokens and elapsed seconds", () => {
    expect(apply(taskStarted(), taskResult()).tasks[0]?.summary).toBe("ok · 120 tokens · 1.5 s");
  });

  it("shows MCP servers, red when down", () => {
    const state = apply(
      { type: "mcp_status", ts: TS, agent: "viernes", server: "filesystem", up: true, reason: null },
      { type: "mcp_status", ts: TS, agent: "viernes", server: "shell", up: false, reason: "no arranca" },
      { type: "mcp_status", ts: TS, agent: "viernes", server: "filesystem", up: false, reason: "caído" },
    );

    expect(state.servers.map((s) => [s.label, s.down])).toEqual([
      ["Viernes - File System - MCP", true],
      ["Viernes - Shell - MCP", true],
    ]);
  });

  it("a server back up is not red", () => {
    const state = apply({ type: "mcp_status", ts: TS, agent: "a", server: "s", up: true, reason: null });

    expect(state.servers.map((s) => [s.label, s.down])).toEqual([["A - S - MCP", false]]);
  });
});

describe("Edith audit", () => {
  const rows: AuditRow[] = [
    { time: "09:00:00", agent: "viernes", tool: "a", verdict: "allow", rule: "r", user_decision: null },
    { time: "09:00:01", agent: "viernes", tool: "b", verdict: "deny", rule: "r", user_decision: null },
    { time: "09:00:02", agent: "viernes", tool: "c", verdict: "confirm", rule: "r", user_decision: "allow" },
  ];

  it("loads today's rows", () => {
    expect(apply({ kind: "audit_loaded", rows }).audit).toEqual(rows);
  });

  it("appends a row for each tool call at its local time", () => {
    const ts = new Date(2026, 10, 1, 11, 5, 7).toISOString();
    const state = apply(toolCall("t9", { ts, verdict: "deny", rule: "r/deny" }));

    expect(state.audit).toEqual([
      { time: "11:05:07", agent: "viernes", tool: "filesystem.read_file", verdict: "deny", rule: "r/deny", user_decision: null },
    ]);
  });

  it.each([
    ["all", ["a", "b", "c"]],
    ["allow", ["a"]],
    ["confirm", ["c"]],
    ["deny", ["b"]],
  ] as const)("filter %s", (filter, tools) => {
    const state = apply({ kind: "audit_loaded", rows }, { kind: "audit_filter", filter });

    expect(visibleAudit(state).map((row) => row.tool)).toEqual(tools);
  });
});

describe("confirmation", () => {
  it("is set by needs_confirmation", () => {
    expect(apply(confirmation()).confirmation?.task_id).toBe("t1");
  });

  it.each([
    ["tool_call", toolCall("t1")],
    ["task result", taskResult("t1")],
  ])("is cleared by a %s of its task", (_name, event) => {
    expect(apply(confirmation(), event).confirmation).toBeNull();
  });

  it("is kept by events of another task", () => {
    expect(apply(confirmation(), toolCall("t2"), taskResult("t2")).confirmation?.task_id).toBe("t1");
  });

  it("is cleared when answered locally", () => {
    expect(apply(confirmation(), { kind: "confirmation_answered" }).confirmation).toBeNull();
  });
});

describe("PIN view", () => {
  it.each(["start", "idle", "wrong_pin", "backoff"])("prompts for %s", (reason) => {
    expect(apply(auth("locked", reason)).pin.mode).toBe("prompt");
  });

  it.each(["unlocked", "not_required", "cancelled", "locked_by_user"])("hides for %s", (reason) => {
    expect(apply(auth("locked", "start"), auth("locked", reason)).pin.mode).toBe("hidden");
  });

  it("explains no_lock_file with tony pin set", () => {
    const pin = apply(auth("locked", "no_lock_file")).pin;

    expect(pin.mode).toBe("explain");
    expect(pin.message).toContain("tony pin set");
  });

  it("keeps the back-off deadline from retry_in_s", () => {
    expect(apply(auth("locked", "wrong_pin", 10)).pin.retryAt).toBe(NOW + 10_000);
  });

  it("can unlock only while locked", () => {
    expect(apply(auth("locked", "cancelled")).pin.canUnlock).toBe(true);
    expect(apply(auth("unlocked", "unlocked"), auth("locked", "locked_by_user")).pin.canUnlock).toBe(true);
    expect(apply(auth("unlocked", "unlocked")).pin.canUnlock).toBe(false);
  });

  it("an unlock request reopens the prompt while locked", () => {
    const pin = apply(auth("locked", "cancelled"), { kind: "unlock_requested" }).pin;

    expect([pin.mode, pin.message]).toEqual(["prompt", "Introduzca el PIN de Edith para permitir tareas delegadas."]);
  });

  it("an unlock request does nothing while unlocked", () => {
    expect(apply(auth("unlocked", "unlocked"), { kind: "unlock_requested" }).pin.mode).toBe("hidden");
  });

  it("keeps the latest auth reason, none before the first auth event", () => {
    expect(initialState().pin.reason).toBeNull();
    expect(apply(auth("locked", "start"), auth("locked", "locked_by_user")).pin.reason).toBe("locked_by_user");
  });

  it("cancelling hides the prompt", () => {
    expect(apply(auth("locked", "start"), { kind: "pin_cancelled" }).pin.mode).toBe("hidden");
  });
});

describe("thinking", () => {
  it.each([
    ["turn_started", turnStarted(true)],
    ["task_started", taskStarted()],
  ])("starts with %s", (_name, event) => {
    expect(apply(event).thinking).toBe(true);
  });

  it("ends with the first token of a writing turn", () => {
    expect(apply(turnStarted(true), token("jarvis", "x")).thinking).toBe(false);
  });

  it("continues through the tokens of a non-writing turn", () => {
    expect(apply(turnStarted(false), token("jarvis", "x"), token("jarvis", "y")).thinking).toBe(true);
  });

  it.each([
    ["the turn result", turnResult("x")],
    ["a front error", error("front")],
  ])("ends with %s", (_name, event) => {
    expect(apply(turnStarted(false), event).thinking).toBe(false);
  });

  it("ends when speech output starts", () => {
    expect(apply(turnStarted(false), { kind: "output_started" }).thinking).toBe(false);
  });

  it("is kept by other errors", () => {
    expect(apply(turnStarted(false), error("listen")).thinking).toBe(true);
  });
});

describe("other events", () => {
  it("unknown event types and voice levels leave the state untouched", () => {
    const before = initialState();
    const unknown = { type: "telepathy", ts: TS } as unknown as CoreEvent;

    expect(reduce(before, { kind: "event", event: unknown, now: NOW })).toBe(before);
    expect(reduce(before, { kind: "event", event: { type: "voice_level", ts: TS, source: "input", level: 1 }, now: NOW })).toBe(before);
  });
});
