import type {
  Envelope,
  HelloOkPayload,
  HistoryMessage,
  PendingConfirmationPayload,
  ReplyMode,
  SttFinalPayload,
  TaskStatus,
  ToolResultPayload,
  UsagePayload,
  VoiceState,
} from "./types";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** seq of the envelope that created it; 0 for messages loaded from the history. */
  seq: number;
  effectiveMode?: string;
  streaming?: boolean;
  /** "voice" when the text came from a transcription (stt.final). */
  source?: "voice";
}

export interface ToolRow {
  tool: string;
  args: unknown;
  done: boolean;
  ok?: boolean;
  durationMs?: number;
  error?: string | null;
}

export interface TaskUsage {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  cumulativeTokens: number;
  alert: boolean;
}

export interface TaskNode {
  taskId: string;
  parentId: string | null;
  agent: string | null;
  status: TaskStatus;
  tools: ToolRow[];
  children: string[];
  logPath: string | null;
  usage?: TaskUsage;
}

export interface PendingConfirmation {
  confirmationId: string;
  taskId: string;
  tool: string;
  args: unknown;
  deadline: number;
}

export interface ReloadEntry {
  agent: string;
  ok: boolean;
  detail: string;
}

export interface UsageTotal {
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

export interface ChatState {
  conversationId: string | null;
  streamId: string | null;
  replyMode: ReplyMode;
  lastSeq: number;
  /** last_seq of the latest hello.ok: events at or below it are replays older than its state. */
  snapshotSeq: number;
  connected: boolean;
  messages: Message[];
  pendingText: string | null;
  pendingClientId: string | null;
  waitText: string | null;
  turnInProgress: boolean;
  tasks: Record<string, TaskNode>;
  activeRootId: string | null;
  lastRootId: string | null;
  confirmation: PendingConfirmation | null;
  usageTotal: UsageTotal;
  alert: boolean;
  reloads: ReloadEntry[];
  notice: string | null;
  resyncRequested: boolean;
  voice: VoiceState;
}

export type Action =
  | { type: "envelope"; envelope: Envelope; now: number }
  | { type: "sent"; text: string; clientId: string }
  | { type: "history"; messages: HistoryMessage[] }
  | { type: "tick"; now: number }
  | { type: "connection"; connected: boolean }
  | { type: "dismiss_notice" }
  | { type: "set_reply_mode"; mode: ReplyMode }
  | { type: "voice_health"; available: boolean; reason: string | null }
  | { type: "mic"; on: boolean }
  | { type: "silence_after_speech" }
  | { type: "playback_drained" }
  | { type: "stop_audio" }
  | { type: "notice"; text: string };

export const EXPIRED_NOTICE = "Confirmación caducada";

const RESULT_STATUS: Record<string, TaskStatus> = {
  ok: "done",
  partial: "done",
  error: "failed",
  cancelled: "cancelled",
  timeout: "timeout",
};

export const initialState: ChatState = {
  conversationId: null,
  streamId: null,
  replyMode: "auto",
  lastSeq: 0,
  snapshotSeq: 0,
  connected: false,
  messages: [],
  pendingText: null,
  pendingClientId: null,
  waitText: null,
  turnInProgress: false,
  tasks: {},
  activeRootId: null,
  lastRootId: null,
  confirmation: null,
  usageTotal: { inputTokens: 0, outputTokens: 0, costUsd: 0 },
  alert: false,
  reloads: [],
  notice: null,
  resyncRequested: false,
  voice: {
    available: null,
    reason: null,
    mic: "off",
    phase: "idle",
    speakingMessageId: null,
  },
};

export function reduce(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "envelope":
      return onEnvelope(state, action.envelope, action.now);
    case "sent":
      return { ...state, pendingText: action.text, pendingClientId: action.clientId, notice: null };
    case "history":
      return { ...state, resyncRequested: false, waitText: null, messages: mergeHistory(state, action.messages) };
    case "tick":
      if (state.confirmation && action.now >= state.confirmation.deadline) {
        return { ...state, confirmation: null, notice: EXPIRED_NOTICE };
      }
      return state;
    case "connection":
      return action.connected ? { ...state, connected: true } : withVoice({ ...state, connected: false }, micOff(state.voice));
    case "dismiss_notice":
      return { ...state, notice: null };
    case "notice":
      return { ...state, notice: action.text };
    case "set_reply_mode":
      return { ...state, replyMode: action.mode };
    case "voice_health":
      return withVoice(state, { available: action.available, reason: action.reason });
    case "mic":
      return withVoice(state, { mic: action.on ? "on" : "off", phase: action.on ? "listening" : "idle" });
    case "silence_after_speech":
      return state.voice.phase === "listening" ? withVoice(state, { phase: "transcribing" }) : state;
    case "playback_drained":
      return state.voice.phase === "speaking" ? state : withVoice(state, { speakingMessageId: null });
    case "stop_audio":
      return withVoice(state, { phase: restingPhase(state.voice), speakingMessageId: null });
  }
}

function withVoice(state: ChatState, patch: Partial<VoiceState>): ChatState {
  return { ...state, voice: { ...state.voice, ...patch } };
}

/** The server drops the audio session on every hello and disconnect, so capture must restart. */
function micOff(voice: VoiceState): Partial<VoiceState> {
  return { mic: "off", phase: voice.phase === "speaking" ? "speaking" : "idle" };
}

/** The phase to return to when nothing is being spoken or transcribed. */
function restingPhase(voice: VoiceState): VoiceState["phase"] {
  return voice.mic === "on" ? "listening" : "idle";
}

/** Loaded history wins for the ids it contains; messages that arrived after the snapshot survive. */
function mergeHistory(state: ChatState, history: HistoryMessage[]): Message[] {
  const loaded: Message[] = history.map((m) => ({
    id: m.id,
    role: m.role === "user" ? "user" : "assistant",
    content: m.content,
    seq: 0,
    effectiveMode: m.reply_mode ?? undefined,
  }));
  const known = new Set(loaded.map((m) => m.id));
  const live = state.messages.filter((m) => m.seq > state.snapshotSeq && !known.has(m.id));
  return [...loaded, ...live];
}

function onEnvelope(state: ChatState, envelope: Envelope, now: number): ChatState {
  if (envelope.type === "hello.ok") {
    return onHello(state, envelope.payload as unknown as HelloOkPayload, now);
  }
  if (envelope.seq > 0 && envelope.seq <= state.lastSeq) {
    return state;
  }
  const next = envelope.seq > 0 ? { ...state, lastSeq: envelope.seq } : { ...state };
  const payload = envelope.payload;
  switch (envelope.type) {
    case "error":
      return onError(next, envelope);
    case "user.accepted":
      return onUserAccepted(next, envelope);
    case "assistant.delta":
      return onDelta(next, envelope);
    case "assistant.wait":
      return { ...next, waitText: String(payload.text ?? "") };
    case "assistant.final":
      return onFinal(next, envelope);
    case "usage":
      return onUsage(next, envelope);
    case "config.reloaded":
      return addReload(next, String(payload.agent), true, (payload.servers as string[]).join(", "));
    case "config.reload_failed":
      return addReload(next, String(payload.agent), false, String(payload.error));
    case "stt.final":
      return onSttFinal(next, envelope);
    case "tts.start":
      return withVoice(next, { phase: "speaking", speakingMessageId: String(envelope.message_id) });
    case "tts.end":
      return withVoice(next, { phase: restingPhase(next.voice) });
    case "tts.cancelled":
      return withVoice(next, { phase: restingPhase(next.voice), speakingMessageId: null });
    default:
      return envelope.task_id ? onTaskEvent(next, envelope, envelope.task_id, now) : next;
  }
}

function onHello(state: ChatState, hello: HelloOkPayload, now: number): ChatState {
  const base = isAnotherConversation(state, hello) ? resetForConversation(state) : state;
  const streamId = hello.stream_id ?? null;
  const restarted = base.streamId !== null && streamId !== null && streamId !== base.streamId;
  const resync = hello.resync === true || restarted || hello.last_seq < base.lastSeq;
  const pending = hello.state.pending_confirmation;
  let tasks = base.tasks;
  let activeRootId: string | null = null;
  for (const task of hello.state.active_tasks) {
    tasks = upsertTask(tasks, task.task_id, task.parent_id, { status: task.status });
    if (task.parent_id === null) {
      activeRootId = task.task_id;
    }
  }
  return {
    ...base,
    conversationId: hello.conversation_id,
    streamId,
    replyMode: hello.reply_mode,
    lastSeq: resync ? hello.last_seq : base.lastSeq,
    snapshotSeq: hello.last_seq,
    connected: true,
    turnInProgress: hello.state.turn_in_progress,
    tasks,
    activeRootId,
    confirmation: pending ? toConfirmation(pending, "front", now) : null,
    resyncRequested: resync,
    voice: { ...base.voice, ...micOff(base.voice) },
  };
}

function isAnotherConversation(state: ChatState, hello: HelloOkPayload): boolean {
  return state.conversationId !== null && hello.conversation_id !== state.conversationId;
}

function resetForConversation(state: ChatState): ChatState {
  return { ...initialState, connected: state.connected, replyMode: state.replyMode, reloads: state.reloads, voice: state.voice };
}

function toConfirmation(
  pending: PendingConfirmationPayload,
  fallbackTaskId: string,
  now: number,
): PendingConfirmation {
  return {
    confirmationId: pending.confirmation_id,
    taskId: pending.task_id ?? fallbackTaskId,
    tool: pending.tool,
    args: pending.args,
    deadline: now + pending.expires_in_s * 1000,
  };
}

function onError(state: ChatState, envelope: Envelope): ChatState {
  const payload = envelope.payload;
  const base = {
    ...state,
    notice: String(payload.detail ?? payload.code ?? "error"),
    pendingText: null,
    pendingClientId: null,
  };
  if (payload.code === "voice_unavailable") {
    return withVoice(base, { available: false, reason: base.notice, mic: "off", phase: "idle" });
  }
  if (payload.code === "unsupported_audio") {
    return withVoice(base, micOff(state.voice));
  }
  if (state.voice.phase === "transcribing") {
    return withVoice(base, { phase: "listening" });
  }
  return base;
}

function onSttFinal(state: ChatState, envelope: Envelope): ChatState {
  const final = envelope.payload as unknown as SttFinalPayload;
  const message: Message = { id: final.message_id, role: "user", content: final.text, seq: envelope.seq, source: "voice" };
  const phase = state.voice.phase === "transcribing" ? "listening" : state.voice.phase;
  return withVoice({ ...state, messages: [...state.messages, message] }, { phase });
}

function onUserAccepted(state: ChatState, envelope: Envelope): ChatState {
  const id = String(envelope.payload.message_id ?? envelope.message_id);
  if (state.messages.some((m) => m.id === id)) {
    const mode = String(envelope.payload.effective_mode);
    const messages = state.messages.map((m) => (m.id === id ? { ...m, effectiveMode: mode } : m));
    return { ...state, messages, turnInProgress: true };
  }
  const clientId = envelope.payload.client_id;
  if (clientId != null && clientId !== state.pendingClientId) {
    return { ...state, turnInProgress: true };
  }
  const message: Message = {
    id: String(envelope.payload.message_id ?? envelope.message_id),
    role: "user",
    content: state.pendingText ?? "",
    seq: envelope.seq,
    effectiveMode: String(envelope.payload.effective_mode),
  };
  return {
    ...state,
    messages: [...state.messages, message],
    pendingText: null,
    pendingClientId: null,
    turnInProgress: true,
  };
}

function onDelta(state: ChatState, envelope: Envelope): ChatState {
  const id = envelope.message_id ?? "";
  const text = String(envelope.payload.text ?? "");
  const existing = state.messages.find((m) => m.id === id);
  const messages = existing
    ? state.messages.map((m) => (m.id === id ? { ...m, content: m.content + text } : m))
    : [...state.messages, { id, role: "assistant" as const, content: text, seq: envelope.seq, streaming: true }];
  return { ...state, messages, turnInProgress: true };
}

function onFinal(state: ChatState, envelope: Envelope): ChatState {
  const id = String(envelope.payload.message_id ?? envelope.message_id);
  const content = String(envelope.payload.display_text ?? "");
  const exists = state.messages.some((m) => m.id === id);
  const final: Message = { id, role: "assistant", content, seq: envelope.seq, streaming: false };
  const messages = exists
    ? state.messages.map((m) => (m.id === id ? { ...final, seq: m.seq } : m))
    : [...state.messages, final];
  return { ...state, messages, waitText: null, turnInProgress: false };
}

function onUsage(state: ChatState, envelope: Envelope): ChatState {
  const usage = envelope.payload as unknown as UsagePayload;
  const total: UsageTotal = {
    inputTokens: state.usageTotal.inputTokens + usage.input_tokens,
    outputTokens: state.usageTotal.outputTokens + usage.output_tokens,
    costUsd: round(state.usageTotal.costUsd + usage.cost_usd),
  };
  const taskId = envelope.task_id ?? null;
  const tasks = taskId
    ? upsertTask(state.tasks, taskId, null, {
        usage: {
          inputTokens: usage.input_tokens,
          outputTokens: usage.output_tokens,
          costUsd: usage.cost_usd,
          cumulativeTokens: usage.cumulative_tokens,
          alert: usage.alert,
        },
      })
    : state.tasks;
  return { ...state, tasks, usageTotal: total, alert: state.alert || usage.alert };
}

function round(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function addReload(state: ChatState, agent: string, ok: boolean, detail: string): ChatState {
  return { ...state, reloads: [...state.reloads, { agent, ok, detail }] };
}

function onTaskEvent(state: ChatState, envelope: Envelope, taskId: string, now: number): ChatState {
  const next = applyTaskEvent(state, envelope, taskId, now);
  const replayed = envelope.seq > 0 && envelope.seq <= state.snapshotSeq;
  return replayed ? { ...next, activeRootId: state.activeRootId, confirmation: state.confirmation } : next;
}

function applyTaskEvent(state: ChatState, envelope: Envelope, taskId: string, now: number): ChatState {
  const payload = envelope.payload;
  const parentId = typeof payload.parent_id === "string" ? payload.parent_id : null;
  let tasks = upsertTask(state.tasks, taskId, parentId, {});
  let next = { ...state, tasks };
  switch (envelope.type) {
    case "task.queued":
      tasks = upsertTask(tasks, taskId, parentId, {
        status: "queued",
        logPath: typeof payload.log_path === "string" ? payload.log_path : null,
      });
      return parentId === null
        ? { ...next, tasks, activeRootId: taskId, alert: false }
        : { ...next, tasks };
    case "task.running":
      return { ...next, tasks: upsertTask(tasks, taskId, parentId, { status: "running" }) };
    case "task.needs_confirmation": {
      const pending = payload as unknown as PendingConfirmationPayload;
      return {
        ...next,
        tasks: upsertTask(tasks, taskId, parentId, { status: "waiting_confirmation" }),
        confirmation: toConfirmation(pending, taskId, now),
      };
    }
    case "task.confirmed":
      return {
        ...next,
        tasks: upsertTask(tasks, taskId, parentId, { status: "running" }),
        confirmation: clearConfirmation(next.confirmation, taskId),
      };
    case "task.cancelled":
      return {
        ...next,
        tasks: upsertTask(tasks, taskId, parentId, { status: "cancelled" }),
        confirmation: clearConfirmation(next.confirmation, taskId),
      };
    case "task.result": {
      const result = payload.result as { status?: string } | undefined;
      const status = RESULT_STATUS[result?.status ?? ""] ?? "done";
      tasks = upsertTask(tasks, taskId, parentId, { status });
      const isRoot = tasks[taskId]?.parentId === null;
      return {
        ...next,
        tasks,
        confirmation: clearConfirmation(next.confirmation, taskId),
        activeRootId: isRoot && next.activeRootId === taskId ? null : next.activeRootId,
        lastRootId: isRoot ? taskId : next.lastRootId,
      };
    }
    case "subtask.started": {
      const childId = String(payload.task_id);
      tasks = upsertTask(tasks, childId, taskId, {
        agent: typeof payload.agent === "string" ? payload.agent : null,
        status: "running",
      });
      return { ...next, tasks };
    }
    case "subtask.finished": {
      const childId = String(payload.task_id);
      const status = (payload.status as TaskStatus | undefined) ?? "done";
      return { ...next, tasks: upsertTask(tasks, childId, taskId, { status }) };
    }
    case "tool.call": {
      const node = tasks[taskId]!;
      const row: ToolRow = { tool: String(payload.tool), args: payload.args, done: false };
      tasks = { ...tasks, [taskId]: { ...node, status: ensureRunning(node.status), tools: [...node.tools, row] } };
      return { ...next, tasks };
    }
    case "tool.result": {
      const node = tasks[taskId]!;
      const result = payload as unknown as ToolResultPayload;
      const index = node.tools.findIndex((t) => !t.done && t.tool === result.tool);
      if (index < 0) {
        return next;
      }
      const tools = node.tools.map((t, i) =>
        i === index
          ? { ...t, done: true, ok: result.ok, durationMs: result.duration_ms, error: result.error }
          : t,
      );
      return { ...next, tasks: { ...tasks, [taskId]: { ...node, tools } } };
    }
    default:
      return next;
  }
}

function ensureRunning(status: TaskStatus): TaskStatus {
  return status === "queued" ? "running" : status;
}

function clearConfirmation(
  confirmation: PendingConfirmation | null,
  taskId: string,
): PendingConfirmation | null {
  return confirmation && confirmation.taskId === taskId ? null : confirmation;
}

function upsertTask(
  tasks: Record<string, TaskNode>,
  taskId: string,
  parentId: string | null,
  patch: Partial<TaskNode>,
): Record<string, TaskNode> {
  const existing = tasks[taskId] ?? {
    taskId,
    parentId,
    agent: null,
    status: "queued" as TaskStatus,
    tools: [],
    children: [],
    logPath: null,
  };
  const effectiveParent = existing.parentId ?? parentId;
  const node: TaskNode = { ...existing, ...patch, parentId: effectiveParent };
  let result = { ...tasks, [taskId]: node };
  if (effectiveParent !== null) {
    const parent = result[effectiveParent] ?? {
      taskId: effectiveParent,
      parentId: null,
      agent: null,
      status: "running" as TaskStatus,
      tools: [],
      children: [],
      logPath: null,
    };
    if (!parent.children.includes(taskId)) {
      result = { ...result, [effectiveParent]: { ...parent, children: [...parent.children, taskId] } };
    }
  }
  return result;
}
