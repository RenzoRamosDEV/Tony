import type { HistoryMessage, ReplyMode, VoiceHealth } from "../protocol/types";

export interface ApiErrorBody {
  error: string;
  detail: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    detail: string,
  ) {
    super(detail);
  }
}

export interface EnginesView {
  active: string;
  worker?: string;
  profiles: { name: string; type: string; model: string | null; auth?: string; configured?: boolean }[];
}

export interface Settings {
  reply_mode: ReplyMode;
  reply_mode_source: "settings" | "yaml";
}

export interface ConversationSummary {
  id: string;
  channel: string;
  created_at: string;
}

export interface MemoryView {
  content: string;
  lines: number;
}

export interface HealthView {
  status: string;
  version: string;
  front: string;
  worker: string;
  mcp: { name: string; state: string; tool_count: number }[];
  voice: VoiceHealth;
}

type Fetch = typeof fetch;

async function request<T>(fetchImpl: Fetch, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetchImpl(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let body: Partial<ApiErrorBody> = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = {};
    }
    throw new ApiError(response.status, body.error ?? "http_error", body.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export function createApi(fetchImpl: Fetch = (...args) => fetch(...args)) {
  return {
    getEngines: () => request<EnginesView>(fetchImpl, "/api/engines"),
    patchEngine: (profile: string) => request<EnginesView>(fetchImpl, "/api/engines", {
      method: "PATCH",
      body: JSON.stringify({ profile }),
    }),
    configureEngine: (profile: string, model: string, apiKey?: string, deleteKey = false) =>
      request<EnginesView>(fetchImpl, `/api/engines/${encodeURIComponent(profile)}/credentials`, {
        method: "PUT",
        body: JSON.stringify({ model, api_key: apiKey || undefined, delete_key: deleteKey }),
      }),
    getHealth: () => request<HealthView>(fetchImpl, "/api/health"),
    getSettings: () => request<Settings>(fetchImpl, "/api/settings"),
    patchSettings: (reply_mode: ReplyMode) =>
      request<Settings>(fetchImpl, "/api/settings", {
        method: "PATCH",
        body: JSON.stringify({ reply_mode }),
      }),
    getConversations: () => request<ConversationSummary[]>(fetchImpl, "/api/conversations"),
    getMessages: (conversationId: string) =>
      request<HistoryMessage[]>(fetchImpl, `/api/conversations/${encodeURIComponent(conversationId)}/messages`),
    confirmTask: (taskId: string, confirmationId: string, approved: boolean) =>
      request<{ ok: true }>(fetchImpl, `/api/tasks/${encodeURIComponent(taskId)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ confirmation_id: confirmationId, approved }),
      }),
    cancelTask: (taskId: string) =>
      request<{ ok: true }>(fetchImpl, `/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
        method: "POST",
      }),
    getMemory: () => request<MemoryView>(fetchImpl, "/api/memory"),
  };
}

export type Api = ReturnType<typeof createApi>;
