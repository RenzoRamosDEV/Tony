export type ReplyMode = "auto" | "voice" | "text" | "both";
export const REPLY_MODES: ReplyMode[] = ["auto", "voice", "text", "both"];

export type TaskStatus =
  | "queued"
  | "running"
  | "waiting_confirmation"
  | "done"
  | "failed"
  | "cancelled"
  | "timeout";

export interface Envelope<P = Record<string, unknown>> {
  v: 1;
  type: string;
  seq: number;
  conversation_id: string | null;
  message_id?: string;
  task_id?: string;
  payload: P;
}

export interface HelloOkPayload {
  conversation_id: string;
  stream_id?: string;
  reply_mode: ReplyMode;
  last_seq: number;
  resync?: boolean;
  state: {
    turn_in_progress: boolean;
    active_tasks: { task_id: string; parent_id: string | null; status: TaskStatus }[];
    pending_confirmation: PendingConfirmationPayload | null;
  };
}

export interface PendingConfirmationPayload {
  confirmation_id: string;
  task_id?: string;
  tool: string;
  args: unknown;
  expires_in_s: number;
}

export interface UsagePayload {
  task_id?: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cumulative_tokens: number;
  alert: boolean;
}

export interface ToolResultPayload {
  tool: string;
  ok: boolean;
  duration_ms: number;
  error: string | null;
}

export interface HistoryMessage {
  id: string;
  role: string;
  content: string;
  reply_mode: string | null;
  created_at: string;
}

export interface ClientMessage {
  type: "hello" | "user.text" | "confirm" | "cancel" | "set_mode";
  payload: Record<string, unknown>;
}
