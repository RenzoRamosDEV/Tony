import { describe, expect, it } from "vitest";

import { initialState, reduce, type ChatState } from "./reducer";
import type { Envelope } from "./types";

let seq = 0;

function env(type: string, payload: Record<string, unknown> = {}, extra: Partial<Envelope> = {}): Envelope {
  seq += 1;
  return { v: 1, type, seq, conversation_id: "c-1", payload, ...extra };
}

function oob(type: string, payload: Record<string, unknown>): Envelope {
  return { v: 1, type, seq: 0, conversation_id: "c-1", payload };
}

function apply(state: ChatState, ...envelopes: Envelope[]): ChatState {
  return envelopes.reduce((s, e) => reduce(s, { type: "envelope", envelope: e, now: 1000 }), state);
}

function fresh(): ChatState {
  seq = 0;
  return apply(
    initialState,
    oob("hello.ok", {
      conversation_id: "c-1",
      reply_mode: "auto",
      last_seq: 0,
      state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null },
    }),
  );
}

describe("seq handling", () => {
  it("discards envelopes with seq lower or equal to the last seen", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "uno" }));
    const stale: Envelope = { v: 1, type: "assistant.wait", seq: 1, conversation_id: "c-1", payload: { text: "dos" } };

    state = apply(state, stale);

    expect(state.lastSeq).toBe(1);
    expect(state.waitText).toBe("uno");
  });

  it("accepts out-of-band envelopes with seq 0", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "uno" }));

    state = apply(state, oob("error", { code: "empty_text", detail: "vacío" }));

    expect(state.notice).toBe("vacío");
    expect(state.lastSeq).toBe(1);
  });

  it("restarts the counter when hello.ok reports a lower last_seq", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "a" }), env("assistant.wait", { text: "b" }));
    expect(state.lastSeq).toBe(2);

    state = apply(state, oob("hello.ok", { conversation_id: "c-1", reply_mode: "auto", last_seq: 0, state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null } }));
    seq = 0;
    state = apply(state, env("assistant.wait", { text: "c" }));

    expect(state.lastSeq).toBe(1);
    expect(state.waitText).toBe("c");
  });

  it("keeps the higher counter when hello.ok reports a higher last_seq", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "a" }));
    state = apply(state, oob("hello.ok", { conversation_id: "c-1", reply_mode: "text", last_seq: 5, state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null } }));
    expect(state.lastSeq).toBe(1);
    expect(state.replyMode).toBe("text");
  });
});

describe("messages", () => {
  it("adds the sent text as a user message when it is accepted", () => {
    let state = fresh();
    state = reduce(state, { type: "sent", text: "hola", clientId: "r-1" });
    state = apply(state, env("user.accepted", { message_id: "u1", effective_mode: "voice" }, { message_id: "u1" }));

    expect(state.messages).toEqual([{ id: "u1", role: "user", content: "hola", effectiveMode: "voice", seq: 1 }]);
    expect(state.turnInProgress).toBe(true);
  });

  it("concatenates deltas and replaces them with the final text", () => {
    let state = fresh();
    state = apply(state, env("assistant.delta", { text: "Hola" }, { message_id: "a1" }));
    expect(state.messages).toEqual([{ id: "a1", role: "assistant", content: "Hola", seq: 1, streaming: true }]);
    state = apply(state, env("assistant.delta", { text: ", Renzo" }, { message_id: "a1" }));
    expect(state.messages[0]?.content).toBe("Hola, Renzo");

    state = apply(state, env("assistant.final", { display_text: "Hola, Renzo.", speech_text: null, message_id: "a1" }, { message_id: "a1" }));

    expect(state.messages).toEqual([{ id: "a1", role: "assistant", content: "Hola, Renzo.", seq: 1, streaming: false }]);
    expect(state.turnInProgress).toBe(false);
  });

  it("final without deltas appends the assistant message", () => {
    let state = fresh();
    state = reduce(state, { type: "sent", text: "hola", clientId: "r-1" });
    state = apply(state, env("user.accepted", { message_id: "u1", effective_mode: "text" }, { message_id: "u1" }));
    state = apply(state, env("assistant.final", { display_text: "Hola.", speech_text: null, message_id: "a1" }, { message_id: "a1" }));

    expect(state.messages.map((m) => [m.id, m.content])).toEqual([["u1", "hola"], ["a1", "Hola."]]);
  });

  it("shows the wait phrase until the final arrives", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "Dame un momento." }));
    expect(state.waitText).toBe("Dame un momento.");

    state = apply(state, env("assistant.final", { display_text: "Listo.", speech_text: null, message_id: "a1" }, { message_id: "a1" }));

    expect(state.waitText).toBeNull();
  });

  it("loads the history first and keeps the streaming text received after the snapshot", () => {
    let state = fresh();
    state = apply(state, env("assistant.delta", { text: "parcial" }, { message_id: "a9" }));

    state = reduce(state, { type: "history", messages: [{ id: "m1", role: "user", content: "antes", reply_mode: null, created_at: "t" }, { id: "m2", role: "assistant", content: "Hola.", reply_mode: "text", created_at: "t" }] });

    expect(state.messages).toEqual([
      { id: "m1", role: "user", content: "antes", effectiveMode: undefined, seq: 0 },
      { id: "m2", role: "assistant", content: "Hola.", effectiveMode: "text", seq: 0 },
      { id: "a9", role: "assistant", content: "parcial", seq: 1, streaming: true },
    ]);
  });
});

describe("task tree", () => {
  function withRoot(): ChatState {
    let state = fresh();
    state = apply(state, env("task.queued", { objetivo: "x", log_path: "logs/20261028/t-9.jsonl" }, { task_id: "t-9" }));
    state = apply(state, env("task.running", {}, { task_id: "t-9" }));
    return state;
  }

  it("tracks the root task with its status and log path", () => {
    const state = withRoot();

    expect(state.tasks["t-9"]).toMatchObject({ taskId: "t-9", parentId: null, agent: null, status: "running", logPath: "logs/20261028/t-9.jsonl", children: [] });
    expect(state.activeRootId).toBe("t-9");
  });

  it("nests subtasks with their agent and final status", () => {
    let state = withRoot();
    state = apply(state, env("subtask.started", { task_id: "s-1", agent: "investigador" }, { task_id: "t-9" }));
    state = apply(state, env("tool.call", { tool: "fs.read", args: {}, parent_id: "t-9" }, { task_id: "s-1" }));
    expect(state.tasks["t-9"]?.children).toEqual(["s-1"]);
    expect(state.tasks["s-1"]).toMatchObject({ parentId: "t-9", agent: "investigador", status: "running" });

    state = apply(state, env("subtask.finished", { task_id: "s-1", status: "done" }, { task_id: "t-9" }));

    expect(state.tasks["s-1"]?.status).toBe("done");
  });

  it("marks waiting_confirmation and the final status from task.result", () => {
    let state = withRoot();
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.write", args: { p: 1 }, expires_in_s: 60 }, { task_id: "t-9" }));
    expect(state.tasks["t-9"]?.status).toBe("waiting_confirmation");
    state = apply(state, env("task.confirmed", { confirmation_id: "a3f", approved: true }, { task_id: "t-9" }));
    expect(state.tasks["t-9"]?.status).toBe("running");

    state = apply(state, env("task.result", { result: { status: "ok" } }, { task_id: "t-9" }));

    expect(state.tasks["t-9"]?.status).toBe("done");
    expect(state.activeRootId).toBeNull();
    expect(state.lastRootId).toBe("t-9");
  });

  it.each([
    ["cancelled", "cancelled"],
    ["error", "failed"],
    ["timeout", "timeout"],
    ["partial", "done"],
  ])("task.result %s becomes %s", (resultStatus, expected) => {
    let state = withRoot();
    state = apply(state, env("task.result", { result: { status: resultStatus } }, { task_id: "t-9" }));
    expect(state.tasks["t-9"]?.status).toBe(expected);
  });

  it("pairs tool calls with their results in order and flags unfinished ones", () => {
    let state = withRoot();
    state = apply(state, env("tool.call", { tool: "fs.read", args: { path: "/n/a.md" } }, { task_id: "t-9" }));
    state = apply(state, env("tool.result", { tool: "fs.read", ok: true, duration_ms: 12, error: null }, { task_id: "t-9" }));
    state = apply(state, env("tool.call", { tool: "fs.write", args: {} }, { task_id: "t-9" }));
    state = apply(state, env("tool.result", { tool: "fs.write", ok: false, duration_ms: 3, error: "timeout" }, { task_id: "t-9" }));
    state = apply(state, env("tool.call", { tool: "fs.list", args: {} }, { task_id: "t-9" }));

    expect(state.tasks["t-9"]?.tools).toEqual([
      { tool: "fs.read", args: { path: "/n/a.md" }, ok: true, durationMs: 12, error: null, done: true },
      { tool: "fs.write", args: {}, ok: false, durationMs: 3, error: "timeout", done: true },
      { tool: "fs.list", args: {}, done: false },
    ]);
  });
});

describe("usage and alert", () => {
  it("records usage per task and accumulates the conversation total", () => {
    let state = fresh();
    state = apply(state, env("task.queued", { objetivo: "x" }, { task_id: "t-9" }));
    state = apply(state, env("usage", { task_id: null, input_tokens: 1200, output_tokens: 80, cost_usd: 0.01, cumulative_tokens: 1280, alert: false }));
    state = apply(state, env("usage", { input_tokens: 41200, output_tokens: 9900, cost_usd: 0.31, cumulative_tokens: 51100, alert: true }, { task_id: "t-9" }));

    expect(state.tasks["t-9"]?.usage).toEqual({ inputTokens: 41200, outputTokens: 9900, costUsd: 0.31, cumulativeTokens: 51100, alert: true });
    expect(state.usageTotal).toEqual({ inputTokens: 42400, outputTokens: 9980, costUsd: 0.32 });
    expect(state.alert).toBe(true);
  });

  it("clears the alert when another root task is queued", () => {
    let state = fresh();
    state = apply(state, env("task.queued", {}, { task_id: "t-9" }));
    state = apply(state, env("usage", { input_tokens: 50000, output_tokens: 1, cost_usd: 0, cumulative_tokens: 50001, alert: true }, { task_id: "t-9" }));
    state = apply(state, env("task.result", { result: { status: "ok" } }, { task_id: "t-9" }));
    expect(state.alert).toBe(true);

    state = apply(state, env("task.queued", {}, { task_id: "t-10" }));

    expect(state.alert).toBe(false);
    expect(state.activeRootId).toBe("t-10");
  });
});

describe("confirmation", () => {
  it("stores the pending confirmation with its deadline and clears it on task.confirmed", () => {
    let state = fresh();
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.move", args: { a: 1 }, expires_in_s: 60 }, { task_id: "t-9" }));

    expect(state.confirmation).toEqual({ confirmationId: "a3f", taskId: "t-9", tool: "fs.move", args: { a: 1 }, deadline: 61000 });

    state = apply(state, env("task.confirmed", { confirmation_id: "a3f", approved: false }, { task_id: "t-9" }));
    expect(state.confirmation).toBeNull();
  });

  it.each(["task.cancelled", "task.result"])("%s withdraws the confirmation", (type) => {
    let state = fresh();
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.move", args: {}, expires_in_s: 60 }, { task_id: "t-9" }));
    state = apply(state, env(type, { reason: "user", result: { status: "cancelled" } }, { task_id: "t-9" }));
    expect(state.confirmation).toBeNull();
  });

  it("expires on tick past the deadline and leaves a notice", () => {
    let state = fresh();
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.move", args: {}, expires_in_s: 60 }, { task_id: "t-9" }));
    state = reduce(state, { type: "tick", now: 60999 });
    expect(state.confirmation).not.toBeNull();

    state = reduce(state, { type: "tick", now: 61000 });

    expect(state.confirmation).toBeNull();
    expect(state.notice).toBe("Confirmación caducada");
  });

  it("restores the pending confirmation from hello.ok state", () => {
    let state = fresh();
    state = apply(state, oob("hello.ok", { conversation_id: "c-1", reply_mode: "auto", last_seq: 7, state: { turn_in_progress: true, active_tasks: [{ task_id: "t-9", parent_id: null, status: "waiting_confirmation" }], pending_confirmation: { confirmation_id: "a3f", task_id: "t-9", tool: "fs.move", args: {}, expires_in_s: 39 } } }));

    expect(state.confirmation).toEqual({ confirmationId: "a3f", taskId: "t-9", tool: "fs.move", args: {}, deadline: 40000 });
    expect(state.turnInProgress).toBe(true);
    expect(state.tasks["t-9"]).toMatchObject({ status: "waiting_confirmation", parentId: null });
    expect(state.activeRootId).toBe("t-9");
  });
});

describe("config, errors and resync", () => {
  it("lists reload events", () => {
    let state = fresh();
    state = apply(state, env("config.reloaded", { agent: "viernes", servers: ["filesystem", "fetch"] }));
    state = apply(state, env("config.reload_failed", { agent: "viernes", error: "json roto" }));

    expect(state.reloads).toEqual([
      { agent: "viernes", ok: true, detail: "filesystem, fetch" },
      { agent: "viernes", ok: false, detail: "json roto" },
    ]);
  });

  it("shows server errors as a notice without touching the messages", () => {
    let state = fresh();
    state = apply(state, env("assistant.final", { display_text: "Hola.", speech_text: null, message_id: "a1" }, { message_id: "a1" }));
    state = apply(state, oob("error", { code: "turn_in_progress", detail: "espera" }));

    expect(state.notice).toBe("espera");
    expect(state.messages).toHaveLength(1);
    expect(reduce(state, { type: "dismiss_notice" }).notice).toBeNull();
  });

  it("marks a resync so the history is reloaded", () => {
    let state = fresh();
    state = apply(state, env("assistant.delta", { text: "x" }, { message_id: "a1" }));
    state = apply(state, oob("hello.ok", { conversation_id: "c-1", reply_mode: "auto", last_seq: 900, resync: true, state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null } }));

    expect(state.resyncRequested).toBe(true);
    expect(state.lastSeq).toBe(900);
    expect(reduce(state, { type: "history", messages: [] }).resyncRequested).toBe(false);
  });

  it("tracks the connection state", () => {
    let state = fresh();
    expect(state.connected).toBe(true);
    state = reduce(state, { type: "connection", connected: false });
    expect(state.connected).toBe(false);
  });

  it("hello.ok sets conversation and reply mode", () => {
    const state = fresh();
    expect(state.conversationId).toBe("c-1");
    expect(state.replyMode).toBe("auto");
    expect(reduce(state, { type: "set_reply_mode", mode: "text" }).replyMode).toBe("text");
  });
});

describe("review of change 04", () => {
  const snapshot = (overrides: Record<string, unknown> = {}) =>
    oob("hello.ok", {
      conversation_id: "c-1",
      stream_id: "s-1",
      reply_mode: "auto",
      last_seq: 0,
      state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null },
      ...overrides,
    });

  it("finding 9: a hello.ok for another conversation resets the client state", () => {
    let state = fresh();
    state = apply(state, env("assistant.final", { display_text: "Hola.", speech_text: null, message_id: "a1" }, { message_id: "a1" }));
    state = apply(state, env("task.queued", { objetivo: "x" }, { task_id: "t-9" }));
    state = reduce(state, { type: "sent", text: "pendiente", clientId: "r-1" });

    state = apply(state, snapshot({ conversation_id: "c-2", stream_id: "s-2" }));

    expect(state.conversationId).toBe("c-2");
    expect(state.lastSeq).toBe(0);
    expect(state.messages).toEqual([]);
    expect(state.tasks).toEqual({});
    expect(state.activeRootId).toBeNull();
    expect(state.pendingText).toBeNull();
    expect(state.connected).toBe(true);
    seq = 0;
    state = apply(state, env("assistant.wait", { text: "nueva" }));
    expect(state.waitText).toBe("nueva");
  });

  it("finding 10: an empty snapshot clears the active root and confirmation but keeps history", () => {
    let state = fresh();
    state = apply(state, env("task.queued", { objetivo: "x" }, { task_id: "t-9" }));
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.move", args: {}, expires_in_s: 60 }, { task_id: "t-9" }));
    expect(state.activeRootId).toBe("t-9");

    state = apply(state, snapshot({ last_seq: 900, resync: true }));

    expect(state.activeRootId).toBeNull();
    expect(state.confirmation).toBeNull();
    expect(state.tasks["t-9"]).toBeDefined();
  });

  it("finding 11: a last_seq regression requests a resync and restarts the counter", () => {
    let state = fresh();
    state = apply(state, env("assistant.wait", { text: "a" }), env("assistant.wait", { text: "b" }));

    state = apply(state, snapshot({ last_seq: 0 }));

    expect(state.resyncRequested).toBe(true);
    expect(state.lastSeq).toBe(0);
  });

  it("finding 11: a new stream_id requests a resync even when last_seq is higher", () => {
    seq = 0;
    let state = apply(initialState, snapshot({ stream_id: "s-1" }));
    state = apply(state, env("assistant.wait", { text: "a" }));

    state = apply(state, snapshot({ stream_id: "s-2", last_seq: 5 }));

    expect(state.resyncRequested).toBe(true);
    expect(state.lastSeq).toBe(5);
  });

  it("finding 11: the same stream_id without regression keeps the counter and needs no resync", () => {
    seq = 0;
    let state = apply(initialState, snapshot({ stream_id: "s-1" }));
    state = apply(state, env("assistant.wait", { text: "a" }));

    state = apply(state, snapshot({ stream_id: "s-1", last_seq: 5 }));

    expect(state.resyncRequested).toBe(false);
    expect(state.lastSeq).toBe(1);
  });

  it("finding 12: a late history keeps the messages received after the snapshot", () => {
    let state = fresh();
    state = apply(state, env("assistant.final", { display_text: "Nuevo.", speech_text: null, message_id: "a2" }, { message_id: "a2" }));

    state = reduce(state, { type: "history", messages: [{ id: "m1", role: "user", content: "antes", reply_mode: null, created_at: "t" }] });

    expect(state.messages.map((m) => [m.id, m.content])).toEqual([
      ["m1", "antes"],
      ["a2", "Nuevo."],
    ]);
  });

  it("finding 12: history replaces messages that it already contains and drops replayed ones", () => {
    let state = apply(initialState, snapshot({ last_seq: 2 }));
    seq = 0;
    state = apply(state, env("assistant.final", { display_text: "viejo", speech_text: null, message_id: "a1" }, { message_id: "a1" }));
    state = apply(state, env("assistant.delta", { text: "parcial" }, { message_id: "a9" }));

    state = reduce(state, { type: "history", messages: [{ id: "a1", role: "assistant", content: "viejo", reply_mode: "text", created_at: "t" }] });

    expect(state.messages.map((m) => m.id)).toEqual(["a1"]);
  });

  it("finding 13: a replayed needs_confirmation keeps the deadline restored from the snapshot", () => {
    let state = apply(
      initialState,
      snapshot({
        last_seq: 3,
        state: {
          turn_in_progress: true,
          active_tasks: [{ task_id: "t-9", parent_id: null, status: "waiting_confirmation" }],
          pending_confirmation: { confirmation_id: "a3f", task_id: "t-9", tool: "fs.move", args: {}, expires_in_s: 10 },
        },
      }),
    );
    expect(state.confirmation?.deadline).toBe(11000);
    seq = 0;

    state = apply(state, env("task.queued", { objetivo: "x" }, { task_id: "t-9" }));
    state = apply(state, env("task.needs_confirmation", { confirmation_id: "a3f", tool: "fs.move", args: {}, expires_in_s: 60 }, { task_id: "t-9" }));

    expect(state.confirmation?.deadline).toBe(11000);
    expect(state.activeRootId).toBe("t-9");
  });

  it("finding 13: replayed terminal events never clear the active state of the snapshot", () => {
    let state = apply(
      initialState,
      snapshot({
        last_seq: 2,
        state: {
          turn_in_progress: true,
          active_tasks: [{ task_id: "t-9", parent_id: null, status: "waiting_confirmation" }],
          pending_confirmation: { confirmation_id: "a3f", task_id: "t-9", tool: "fs.move", args: {}, expires_in_s: 10 },
        },
      }),
    );
    seq = 0;

    state = apply(state, env("task.result", { result: { status: "ok" } }, { task_id: "t-8" }));
    state = apply(state, env("task.cancelled", { reason: "user" }, { task_id: "t-9" }));

    expect(state.activeRootId).toBe("t-9");
    expect(state.confirmation?.confirmationId).toBe("a3f");
    expect(state.tasks["t-8"]?.status).toBe("done");
  });

  it("finding 14: sent blocks the composer until the matching user.accepted arrives", () => {
    let state = fresh();
    state = reduce(state, { type: "sent", text: "hola", clientId: "r-1" });
    expect(state.pendingText).toBe("hola");

    state = apply(state, env("user.accepted", { message_id: "u1", effective_mode: "text", client_id: "r-1" }, { message_id: "u1" }));

    expect(state.pendingText).toBeNull();
    expect(state.messages).toEqual([{ id: "u1", role: "user", content: "hola", effectiveMode: "text", seq: 1 }]);
  });

  it("finding 14: an error after sent releases the composer without adding a message", () => {
    let state = fresh();
    state = reduce(state, { type: "sent", text: "hola", clientId: "r-1" });

    state = apply(state, oob("error", { code: "turn_in_progress", detail: "espera" }));

    expect(state.pendingText).toBeNull();
    expect(state.messages).toEqual([]);
  });

  it("finding 14: an acceptance of another request does not consume the pending text", () => {
    let state = fresh();
    state = reduce(state, { type: "sent", text: "hola", clientId: "r-2" });

    state = apply(state, env("user.accepted", { message_id: "u1", effective_mode: "text", client_id: "r-1" }, { message_id: "u1" }));

    expect(state.pendingText).toBe("hola");
    expect(state.messages).toEqual([]);
  });
});

describe("voice", () => {
  function listening(): ChatState {
    let state = fresh();
    state = reduce(state, { type: "voice_health", available: true, reason: null });
    return reduce(state, { type: "mic", on: true });
  }

  it("starts unknown, then takes the availability from /api/health", () => {
    expect(fresh().voice).toEqual({
      available: null,
      reason: null,
      mic: "off",
      phase: "idle",
      speakingMessageId: null,
    });

    const state = reduce(fresh(), { type: "voice_health", available: false, reason: "sin extra" });

    expect(state.voice.available).toBe(false);
    expect(state.voice.reason).toBe("sin extra");
  });

  it("a voice_unavailable error disables the microphone with its reason", () => {
    const state = apply(listening(), oob("error", { code: "voice_unavailable", detail: "falta kokoro: uv sync --extra voice" }));

    expect(state.voice).toMatchObject({ available: false, reason: "falta kokoro: uv sync --extra voice", mic: "off", phase: "idle" });
    expect(state.notice).toBe("falta kokoro: uv sync --extra voice");
  });

  it("mic on means listening and mic off means idle", () => {
    const on = listening();
    expect(on.voice).toMatchObject({ mic: "on", phase: "listening" });

    const off = reduce(on, { type: "mic", on: false });

    expect(off.voice).toMatchObject({ mic: "off", phase: "idle" });
  });

  it("stt.final adds a voice user message and user.accepted sets its mode", () => {
    let state = listening();
    state = reduce(state, { type: "silence_after_speech" });
    expect(state.voice.phase).toBe("transcribing");

    state = apply(state, env("stt.final", { text: "¿qué hora es?", message_id: "m-1" }, { message_id: "m-1" }));
    expect(state.messages).toEqual([{ id: "m-1", role: "user", content: "¿qué hora es?", seq: 1, source: "voice" }]);
    expect(state.voice.phase).toBe("listening");

    state = apply(state, env("user.accepted", { message_id: "m-1", effective_mode: "voice", client_id: null }, { message_id: "m-1" }));

    expect(state.messages).toEqual([{ id: "m-1", role: "user", content: "¿qué hora es?", seq: 1, source: "voice", effectiveMode: "voice" }]);
    expect(state.turnInProgress).toBe(true);
  });

  it("silence after speech only matters while listening", () => {
    const idle = reduce(fresh(), { type: "silence_after_speech" });

    expect(idle.voice.phase).toBe("idle");
  });

  it("tts.start speaks and tts.end returns to listening while the playback goes on", () => {
    let state = listening();
    state = apply(state, env("tts.start", { message_id: "a-2" }, { message_id: "a-2" }));
    expect(state.voice).toMatchObject({ phase: "speaking", speakingMessageId: "a-2" });

    state = apply(state, env("tts.chunk.meta", { seq: 3, sentence_index: 1 }, { message_id: "a-2" }));
    state = apply(state, env("tts.end", { message_id: "a-2" }, { message_id: "a-2" }));

    expect(state.voice).toMatchObject({ phase: "listening", speakingMessageId: "a-2" });
  });

  it("tts.cancelled returns to idle when the microphone is off", () => {
    let state = reduce(fresh(), { type: "voice_health", available: true, reason: null });
    state = apply(state, env("tts.start", { message_id: "a-2" }, { message_id: "a-2" }));
    state = apply(state, env("tts.chunk.meta", { seq: 0, sentence_index: 0 }, { message_id: "a-2" }));

    state = apply(state, env("tts.cancelled", { message_id: "a-2" }, { message_id: "a-2" }));

    expect(state.voice).toMatchObject({ phase: "idle", speakingMessageId: null });
  });

  it("a local stop ends the speaking phase at once", () => {
    let state = listening();
    state = apply(state, env("tts.start", { message_id: "a-2" }, { message_id: "a-2" }));

    state = reduce(state, { type: "stop_audio" });

    expect(state.voice).toMatchObject({ phase: "listening", speakingMessageId: null });
  });

  it("a transcription error returns from transcribing to listening", () => {
    let state = reduce(listening(), { type: "silence_after_speech" });

    state = apply(state, oob("error", { code: "stt_failed", detail: "boom" }));

    expect(state.voice.phase).toBe("listening");
  });
});

describe("local notices", () => {
  it("a local notice shows like a server error and can be dismissed", () => {
    let state = reduce(fresh(), { type: "notice", text: "No se pudo acceder al micrófono" });
    expect(state.notice).toBe("No se pudo acceder al micrófono");

    state = reduce(state, { type: "dismiss_notice" });

    expect(state.notice).toBeNull();
  });
});

describe("voice (review of change 05)", () => {
  function listeningAgain(): ChatState {
    const state = reduce(fresh(), { type: "voice_health", available: true, reason: null });
    return reduce(state, { type: "mic", on: true });
  }

  it("finding 11: the spoken message is kept until the playback drains after tts.end", () => {
    let state = apply(listeningAgain(), env("tts.start", { message_id: "a-3" }, { message_id: "a-3" }));
    state = reduce(state, { type: "playback_drained" });
    expect(state.voice.speakingMessageId).toBe("a-3");

    state = apply(state, env("tts.end", { message_id: "a-3" }, { message_id: "a-3" }));
    expect(state.voice.speakingMessageId).toBe("a-3");
    state = reduce(state, { type: "playback_drained" });

    expect(state.voice).toMatchObject({ phase: "listening", speakingMessageId: null });
  });

  it("finding 10: losing the connection turns the microphone off", () => {
    const state = reduce(listeningAgain(), { type: "connection", connected: false });

    expect(state.voice).toMatchObject({ mic: "off", phase: "idle" });
  });

  it("finding 10: every hello.ok starts with the microphone off", () => {
    const state = apply(listeningAgain(), {
      v: 1,
      type: "hello.ok",
      seq: 0,
      conversation_id: "c-2",
      payload: { conversation_id: "c-2", reply_mode: "auto", last_seq: 0, state: { turn_in_progress: false, active_tasks: [], pending_confirmation: null } },
    });

    expect(state.voice).toMatchObject({ mic: "off", phase: "idle" });
  });

  it("finding 9: an unsupported_audio error turns the microphone off", () => {
    const state = apply(listeningAgain(), oob("error", { code: "unsupported_audio", detail: "formato" }));

    expect(state.voice).toMatchObject({ mic: "off", phase: "idle", available: true });
  });
});
