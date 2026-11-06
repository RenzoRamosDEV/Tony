import type {
  AudioDeviceOption,
  AudioDevicesEvent,
  AuditRow,
  AuthEvent,
  CoreEvent,
  McpStatusEvent,
  NeedsConfirmationEvent,
  ReplyMode,
  TaskResultEvent,
  ToolCallEvent,
  UserDecision,
  Verdict,
  VoiceStateName,
} from "../bridge/types";

export const AGENT_COLOURS: Record<string, string> = {
  jarvis: "#2F6FED",
  viernes: "#2E9E5B",
  edith: "#E0A100",
};
export const NEUTRAL = "#6B7280";
const RUNNING = "en curso";
const VOICE_LABEL = "Tú (voz)";

const PIN_MESSAGES: Record<string, string> = {
  start: "Introduzca el PIN de Edith para permitir tareas delegadas.",
  idle: "La sesión de Edith se ha bloqueado por inactividad. Introduzca el PIN.",
  wrong_pin: "PIN incorrecto.",
  backoff: "Demasiados intentos: espere antes de volver a probar.",
  no_lock_file:
    "No hay PIN de Edith: Tony funciona en modo solo conversación. " +
    "Ejecute `tony pin set` en una terminal para permitir tareas delegadas.",
};
const ASKING_PIN = new Set(["start", "idle", "wrong_pin", "backoff"]);

const MIC_TOOLTIPS: Record<Exclude<VoiceStateName, "unavailable">, string> = {
  loading: "Cargando los modelos de voz…",
  ready: "Pulse para decir una frase",
  listening: "Escuchando: pulse para parar",
};

export type MessageKind = "user" | "agent" | "system";

export interface ChatMessage {
  id: number;
  kind: MessageKind;
  agent: string;
  label: string;
  colour: string;
  text: string;
  open: boolean;
}

export interface ToolNode {
  tool: string;
  verdict: Verdict;
  user_decision: UserDecision | null;
  label: string;
}

export interface SubagentNode {
  name: string;
  calls: ToolNode[];
}

export interface TaskNode {
  task_id: string;
  agent: string;
  objetivo: string;
  label: string;
  calls: ToolNode[];
  subagents: SubagentNode[];
  summary: string;
}

export interface ServerRow {
  agent: string;
  server: string;
  down: boolean;
  label: string;
}

export type AuditFilter = "all" | Verdict;
export type PinMode = "hidden" | "prompt" | "explain";

export interface PinView {
  mode: PinMode;
  message: string;
  /** Epoch milliseconds when the PIN can be typed again. */
  retryAt: number;
  canUnlock: boolean;
}

export interface AudioDevicesView {
  input: AudioDeviceOption[];
  output: AudioDeviceOption[];
  selectedInput: string | null;
  selectedOutput: string | null;
  inputWarning: string | null;
  outputWarning: string | null;
}

export interface UiState {
  messages: ChatMessage[];
  nextId: number;
  writes: boolean;
  replyMode: ReplyMode;
  voice: { state: VoiceStateName; reason: string | null };
  tasks: TaskNode[];
  servers: ServerRow[];
  audit: AuditRow[];
  auditFilter: AuditFilter;
  confirmation: NeedsConfirmationEvent | null;
  pin: PinView;
  thinking: boolean;
  audioDevices: AudioDevicesView;
}

export type UiAction =
  | { kind: "event"; event: CoreEvent; now: number }
  | { kind: "sent"; text: string }
  | { kind: "audit_loaded"; rows: AuditRow[] }
  | { kind: "audit_filter"; filter: AuditFilter }
  | { kind: "confirmation_answered" }
  | { kind: "pin_cancelled" }
  | { kind: "unlock_requested" }
  | { kind: "output_started" };

export function initialState(): UiState {
  return {
    messages: [],
    nextId: 1,
    writes: true,
    replyMode: "auto",
    voice: { state: "loading", reason: null },
    tasks: [],
    servers: [],
    audit: [],
    auditFilter: "all",
    confirmation: null,
    pin: { mode: "hidden", message: "", retryAt: 0, canUnlock: false },
    thinking: false,
    audioDevices: {
      input: [],
      output: [],
      selectedInput: null,
      selectedOutput: null,
      inputWarning: null,
      outputWarning: null,
    },
  };
}

function onAudioDevices(state: UiState, event: AudioDevicesEvent): UiState {
  return {
    ...state,
    audioDevices: {
      input: event.input,
      output: event.output,
      selectedInput: event.selected_input,
      selectedOutput: event.selected_output,
      inputWarning: event.input_fallback_warning,
      outputWarning: event.output_fallback_warning,
    },
  };
}

export function micView(voice: UiState["voice"]): { enabled: boolean; label: string; tooltip: string } {
  const { state, reason } = voice;
  return {
    enabled: state === "ready" || state === "listening",
    label: state === "listening" ? "Escuchando…" : "Micrófono",
    tooltip: state === "unavailable" ? `Voz no disponible: ${reason}` : MIC_TOOLTIPS[state],
  };
}

export function visibleAudit(state: UiState): AuditRow[] {
  return state.audit.filter((row) => state.auditFilter === "all" || row.verdict === state.auditFilter);
}

function title(agent: string): string {
  return agent.charAt(0).toUpperCase() + agent.slice(1);
}

function closeAll(messages: ChatMessage[]): ChatMessage[] {
  return messages.some((m) => m.open) ? messages.map((m) => (m.open ? { ...m, open: false } : m)) : messages;
}

function addMessage(state: UiState, kind: MessageKind, agent: string, label: string, text: string, open = false): UiState {
  const message: ChatMessage = {
    id: state.nextId,
    kind,
    agent,
    label,
    colour: AGENT_COLOURS[agent] ?? NEUTRAL,
    text,
    open,
  };
  return { ...state, messages: [...closeAll(state.messages), message], nextId: state.nextId + 1 };
}

function growMessage(state: UiState, agent: string, text: string): UiState {
  const last = state.messages[state.messages.length - 1];
  if (last === undefined || !last.open || last.agent !== agent) {
    return addMessage(state, "agent", agent, title(agent), text, true);
  }
  return { ...state, messages: [...state.messages.slice(0, -1), { ...last, text: last.text + text }] };
}

function finishTurn(state: UiState, agent: string, text: string): UiState {
  const ended = { ...state, writes: true, thinking: false };
  if (state.messages[state.messages.length - 1]?.open) {
    return { ...ended, messages: closeAll(state.messages) };
  }
  return text ? addMessage(ended, "agent", agent, title(agent), text) : ended;
}

function localTime(ts: string): string {
  const date = new Date(ts);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

function toolNode(event: ToolCallEvent): ToolNode {
  const decision = event.user_decision ? ` (${event.user_decision})` : "";
  return {
    tool: event.tool,
    verdict: event.verdict,
    user_decision: event.user_decision,
    label: `${event.tool} — ${event.verdict}${decision}`,
  };
}

function withCall(task: TaskNode, event: ToolCallEvent): TaskNode {
  const node = toolNode(event);
  const slash = event.agent.indexOf("/");
  if (slash < 0) {
    return { ...task, calls: [...task.calls, node] };
  }
  const name = event.agent.slice(slash + 1);
  const exists = task.subagents.some((sub) => sub.name === name);
  const subagents = exists
    ? task.subagents.map((sub) => (sub.name === name ? { ...sub, calls: [...sub.calls, node] } : sub))
    : [...task.subagents, { name, calls: [node] }];
  return { ...task, subagents };
}

function summary(event: TaskResultEvent): string {
  const tokens = event.input_tokens + event.output_tokens;
  return `${event.outcome} · ${tokens} tokens · ${(event.elapsed_ms / 1000).toFixed(1)} s`;
}

function updateTask(state: UiState, taskId: string, update: (task: TaskNode) => TaskNode): TaskNode[] {
  return state.tasks.map((task) => (task.task_id === taskId ? update(task) : task));
}

function clearConfirmationOf(state: UiState, taskId: string): NeedsConfirmationEvent | null {
  return state.confirmation?.task_id === taskId ? null : state.confirmation;
}

function onToolCall(state: UiState, event: ToolCallEvent): UiState {
  const row: AuditRow = {
    time: localTime(event.ts),
    agent: event.agent,
    tool: event.tool,
    verdict: event.verdict,
    rule: event.rule,
    user_decision: event.user_decision,
  };
  return {
    ...state,
    tasks: updateTask(state, event.task_id, (task) => withCall(task, event)),
    audit: [...state.audit, row],
    confirmation: clearConfirmationOf(state, event.task_id),
  };
}

function onServer(state: UiState, event: McpStatusEvent): UiState {
  const row: ServerRow = {
    agent: event.agent,
    server: event.server,
    down: !event.up,
    label: `${event.agent}/${event.server} — ${event.up ? "activo" : `caído: ${event.reason}`}`,
  };
  const same = (s: ServerRow) => s.agent === row.agent && s.server === row.server;
  const servers = state.servers.some(same)
    ? state.servers.map((s) => (same(s) ? row : s))
    : [...state.servers, row];
  return { ...state, servers };
}

function onAuth(state: UiState, event: AuthEvent, now: number): UiState {
  const mode: PinMode = ASKING_PIN.has(event.reason)
    ? "prompt"
    : event.reason === "no_lock_file"
      ? "explain"
      : "hidden";
  return {
    ...state,
    pin: {
      mode,
      message: PIN_MESSAGES[event.reason] ?? "",
      retryAt: now + event.retry_in_s * 1000,
      canUnlock: event.state === "locked",
    },
  };
}

function onEvent(state: UiState, event: CoreEvent, now: number): UiState {
  switch (event.type) {
    case "turn_started":
      return { ...state, writes: event.writes, thinking: true };
    case "task_started": {
      const task: TaskNode = {
        task_id: event.task_id,
        agent: event.agent,
        objetivo: event.objetivo,
        label: `${event.agent}: ${event.objetivo}`,
        calls: [],
        subagents: [],
        summary: RUNNING,
      };
      return { ...state, tasks: [...state.tasks.filter((t) => t.task_id !== task.task_id), task], thinking: true };
    }
    case "token":
      return state.writes ? { ...growMessage(state, event.agent, event.text), thinking: false } : state;
    case "result":
      if (event.scope === "turn") {
        return finishTurn(state, event.agent, event.text);
      }
      return {
        ...state,
        tasks: updateTask(state, event.task_id, (task) => ({ ...task, summary: summary(event) })),
        confirmation: clearConfirmationOf(state, event.task_id),
      };
    case "transcript":
      return addMessage(state, "user", "user", VOICE_LABEL, event.text);
    case "progress":
      return addMessage(state, "agent", event.agent, title(event.agent), event.text);
    case "error": {
      const front = event.source === "front";
      const next = addMessage(state, "system", "system", "Tony", `Error (${event.source}): ${event.message}`);
      return front ? { ...next, writes: true, thinking: false } : next;
    }
    case "reply_mode":
      return { ...state, replyMode: event.mode };
    case "voice_state":
      return { ...state, voice: { state: event.state, reason: event.reason } };
    case "tool_call":
      return onToolCall(state, event);
    case "mcp_status":
      return onServer(state, event);
    case "needs_confirmation":
      return { ...state, confirmation: event };
    case "auth":
      return onAuth(state, event, now);
    case "audio_devices":
      return onAudioDevices(state, event);
    default:
      return state;
  }
}

export function reduce(state: UiState, action: UiAction): UiState {
  switch (action.kind) {
    case "event":
      return onEvent(state, action.event, action.now);
    case "sent":
      return addMessage(state, "user", "user", "Tú", action.text);
    case "audit_loaded":
      return { ...state, audit: [...action.rows, ...state.audit] };
    case "audit_filter":
      return { ...state, auditFilter: action.filter };
    case "confirmation_answered":
      return { ...state, confirmation: null };
    case "pin_cancelled":
      return { ...state, pin: { ...state.pin, mode: "hidden" } };
    case "unlock_requested":
      return state.pin.canUnlock
        ? { ...state, pin: { ...state.pin, mode: "prompt", message: PIN_MESSAGES.start ?? "" } }
        : state;
    case "output_started":
      return state.thinking ? { ...state, thinking: false } : state;
  }
}
