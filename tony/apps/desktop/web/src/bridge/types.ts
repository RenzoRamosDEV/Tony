/** Mirrors tony/core/events/core_events.py and tony/core/orchestrator/commands.py. */

export type ReplyMode = "auto" | "voice" | "text" | "both";
export type Origin = "text" | "voice";
export type VoiceStateName = "loading" | "ready" | "listening" | "unavailable";
export type AuthState = "locked" | "unlocked";
export type AuthReason =
  | "start"
  | "no_lock_file"
  | "wrong_pin"
  | "backoff"
  | "idle"
  | "cancelled"
  | "locked_by_user"
  | "unlocked"
  | "not_required";
export type Verdict = "allow" | "confirm" | "deny";
export type UserDecision = "allow" | "deny" | "timeout";
export type Outcome = "ok" | "error" | "timeout" | "cancelled";
export type ConfirmDecision = "allow" | "deny" | "always";

interface Base {
  ts: string;
}

export interface TokenEvent extends Base {
  type: "token";
  agent: string;
  text: string;
}
export interface ProgressEvent extends Base {
  type: "progress";
  agent: string;
  text: string;
}
export interface TaskStartedEvent extends Base {
  type: "task_started";
  task_id: string;
  agent: string;
  objetivo: string;
  origin?: "routine";
}
export interface ToolCallEvent extends Base {
  type: "tool_call";
  task_id: string;
  agent: string;
  tool: string;
  args_preview: string;
  verdict: Verdict;
  rule: string;
  user_decision: UserDecision | null;
}
export interface NeedsConfirmationEvent extends Base {
  type: "needs_confirmation";
  task_id: string;
  tool: string;
  args_preview: string;
  question: string;
  allow_always: boolean;
  approval_id?: string;
  args_digest?: string;
  policy_version?: string;
  expires_at?: string;
  preview?: Record<string, string | number>;
}
export interface TaskResultEvent extends Base {
  type: "result";
  scope: "task";
  task_id: string;
  agent: string;
  outcome: Outcome;
  result: { resumen: string; [key: string]: unknown };
  input_tokens: number;
  output_tokens: number;
  elapsed_ms: number;
}
export interface TurnResultEvent extends Base {
  type: "result";
  scope: "turn";
  agent: string;
  text: string;
  reply_mode: ReplyMode;
}
export interface TokenAlertEvent extends Base {
  type: "token_alert";
  task_id: string;
  total_tokens: number;
  limit: number;
}
export interface McpStatusEvent extends Base {
  type: "mcp_status";
  agent: string;
  server: string;
  up: boolean;
  reason: string | null;
}
export interface ErrorEvent extends Base {
  type: "error";
  source: string;
  message: string;
}
export interface AuthEvent extends Base {
  type: "auth";
  state: AuthState;
  reason: AuthReason;
  retry_in_s: number;
}
export interface ReplyModeEvent extends Base {
  type: "reply_mode";
  mode: ReplyMode;
}
export interface TurnStartedEvent extends Base {
  type: "turn_started";
  agent: string;
  origin: Origin;
  reply_mode: ReplyMode;
  speaks: boolean;
  writes: boolean;
}
export interface TranscriptEvent extends Base {
  type: "transcript";
  text: string;
}
export interface VoiceStateEvent extends Base {
  type: "voice_state";
  state: VoiceStateName;
  reason: string | null;
}
export interface VoiceLevelEvent extends Base {
  type: "voice_level";
  source: "input" | "output";
  level: number;
}
export interface AudioDeviceOption {
  name: string;
  is_default: boolean;
}
export interface AudioDevicesEvent extends Base {
  type: "audio_devices";
  input: AudioDeviceOption[];
  output: AudioDeviceOption[];
  selected_input: string | null;
  selected_output: string | null;
  input_fallback_warning: string | null;
  output_fallback_warning: string | null;
}

export type CoreEvent =
  | TokenEvent
  | ProgressEvent
  | TaskStartedEvent
  | ToolCallEvent
  | NeedsConfirmationEvent
  | TaskResultEvent
  | TurnResultEvent
  | TokenAlertEvent
  | McpStatusEvent
  | ErrorEvent
  | AuthEvent
  | ReplyModeEvent
  | TurnStartedEvent
  | TranscriptEvent
  | VoiceStateEvent
  | VoiceLevelEvent
  | AudioDevicesEvent;

export type Command =
  | { type: "send_message"; text: string; origin?: Origin }
  | { type: "confirm"; task_id: string; decision: ConfirmDecision; approval_id?: string }
  | { type: "cancel" }
  | { type: "set_mode"; mode: ReplyMode }
  | { type: "unlock"; pin: string | null }
  | { type: "lock" }
  | { type: "listen" }
  | { type: "stop_listening" }
  | { type: "list_devices" }
  | { type: "set_audio_device"; kind: "input" | "output"; device: string | null };

export interface AuditRow {
  time: string;
  agent: string;
  tool: string;
  verdict: Verdict;
  rule: string;
  user_decision: UserDecision | null;
}

export type ResizeEdge = "top" | "bottom" | "left" | "right" | "top-left" | "top-right" | "bottom-left" | "bottom-right";

/** The window's own chrome, since the OS no longer draws a titlebar (see WindowControls). */
export interface WindowBridge {
  minimize(): void;
  toggleMaximize(): void;
  close(): void;
  startMove(): void;
  startResize(edge: ResizeEdge): void;
}

/** What the page needs from the desktop window. */
export interface TonyBridge {
  /** Attach the event handler; the first call announces the page as ready. */
  onEvent(handler: (event: CoreEvent) => void): void;
  onFocusConfirmation(handler: () => void): void;
  send(command: Command): void;
  auditToday(): Promise<AuditRow[]>;
  /** Present only inside the desktop window, never in a plain browser tab. */
  window: WindowBridge | null;
}
