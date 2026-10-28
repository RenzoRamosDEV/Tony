import { describe, expect, it } from "vitest";

import { ApiError, createApi } from "./client";

function fakeFetch(status: number, body: unknown, calls: { url: string; init?: RequestInit }[]) {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  };
}

describe("api client", () => {
  it("patches the reply mode with a JSON body and same-origin credentials", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const api = createApi(fakeFetch(200, { reply_mode: "voice", reply_mode_source: "settings" }, calls));

    const settings = await api.patchSettings("voice");

    expect(settings.reply_mode).toBe("voice");
    expect(calls[0]?.url).toBe("/api/settings");
    expect(calls[0]?.init?.method).toBe("PATCH");
    expect(calls[0]?.init?.credentials).toBe("same-origin");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ reply_mode: "voice" });
  });

  it("raises ApiError with the server code and detail", async () => {
    const api = createApi(fakeFetch(422, { error: "validation_error", detail: "modo inválido" }, []));

    await expect(api.patchSettings("voice")).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "modo inválido",
    });
    await expect(api.patchSettings("voice")).rejects.toBeInstanceOf(ApiError);
  });

  it("builds the task and conversation urls", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const api = createApi(fakeFetch(200, { ok: true }, calls));

    await api.confirmTask("t 9", "a3f", false);
    await api.cancelTask("t-9");
    await api.getMessages("c/1");
    await api.getMemory();

    expect(calls.map((c) => c.url)).toEqual([
      "/api/tasks/t%209/confirm",
      "/api/tasks/t-9/cancel",
      "/api/conversations/c%2F1/messages",
      "/api/memory",
    ]);
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ confirmation_id: "a3f", approved: false });
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    const api = createApi(async () => new Response("boom", { status: 500, statusText: "Internal" }));

    await expect(api.getSettings()).rejects.toMatchObject({ code: "http_error", message: "Internal" });
  });
});
