import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initialState, reduce, type ChatState } from "../protocol/reducer";
import type { Envelope } from "../protocol/types";
import { DebugPanel } from "./DebugPanel";

let seq = 0;

function env(type: string, payload: Record<string, unknown>, extra: Partial<Envelope> = {}): Envelope {
  seq += 1;
  return { v: 1, type, seq, conversation_id: "c-1", payload, ...extra };
}

function stateWith(...envelopes: Envelope[]): ChatState {
  return envelopes.reduce((s, e) => reduce(s, { type: "envelope", envelope: e, now: 0 }), initialState);
}

function taskState(): ChatState {
  seq = 0;
  return stateWith(
    env("usage", { task_id: null, input_tokens: 1200, output_tokens: 80, cost_usd: 0.01, cumulative_tokens: 1280, alert: false }),
    env("task.queued", { objetivo: "x", log_path: "logs/20261028/t-9.jsonl" }, { task_id: "t-9" }),
    env("task.running", {}, { task_id: "t-9" }),
    env("subtask.started", { task_id: "s-1", agent: "investigador" }, { task_id: "t-9" }),
    env("tool.call", { tool: "filesystem.read_file", args: { path: "/n/a.md" } }, { task_id: "t-9" }),
    env("tool.result", { tool: "filesystem.read_file", ok: true, duration_ms: 12, error: null }, { task_id: "t-9" }),
    env("tool.call", { tool: "fs.write", args: {} }, { task_id: "t-9" }),
    env("tool.result", { tool: "fs.write", ok: false, duration_ms: 3, error: "timeout" }, { task_id: "t-9" }),
    env("tool.call", { tool: "fs.list", args: {} }, { task_id: "t-9" }),
    env("subtask.finished", { task_id: "s-1", status: "done" }, { task_id: "t-9" }),
    env("usage", { input_tokens: 41200, output_tokens: 9900, cost_usd: 0.31, cumulative_tokens: 51100, alert: true }, { task_id: "t-9" }),
    env("config.reloaded", { agent: "viernes", servers: ["filesystem", "fetch"] }),
  );
}

describe("DebugPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("toggles with an accessible button and persists the collapsed state", async () => {
    const { unmount } = render(<DebugPanel state={initialState} storage={window.localStorage} />);
    const toggle = screen.getByRole("button", { name: "Plegar panel de debug" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(toggle);

    expect(screen.getByRole("button", { name: "Desplegar panel de debug" })).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("tony.debug_open")).toBe("false");
    unmount();
    render(<DebugPanel state={initialState} storage={window.localStorage} />);
    expect(screen.getByRole("button", { name: "Desplegar panel de debug" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the task tree with children, agents and statuses", () => {
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    const tree = screen.getByRole("tree");
    expect(tree).toHaveTextContent("t-9");
    expect(screen.getByText("t-9").closest("li")).toHaveTextContent("running");
    expect(screen.getByText("s-1 · investigador").closest("li")).toHaveTextContent("done");
  });

  it("lists the tool calls with args, duration, errors and pending ones", () => {
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    const rows = screen.getAllByRole("listitem").filter((li) => li.closest(".tool-list"));
    expect(rows[0]).toHaveTextContent("filesystem.read_file");
    expect(rows[0]).toHaveTextContent('"path": "/n/a.md"');
    expect(rows[0]).toHaveTextContent("12 ms");
    expect(rows[1]).toHaveTextContent("timeout");
    expect(rows[1]?.querySelector(".warn")).toHaveTextContent("timeout");
    expect(rows[2]).toHaveTextContent("en curso");
  });

  it("shows the counters per task and the conversation total with the alert", () => {
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    expect(screen.getByText("41 200 / 9 900")).toBeInTheDocument();
    expect(screen.getByText("0,31 USD")).toBeInTheDocument();
    expect(screen.getByText(/52 380/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Tarea > 50 k tokens");
  });

  it("withdraws the alert when another task starts", () => {
    const next = reduce(taskState(), { type: "envelope", envelope: env("task.queued", {}, { task_id: "t-10" }), now: 0 });
    render(<DebugPanel state={next} storage={window.localStorage} />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("tree")).toHaveTextContent("t-10");
  });

  it("shows the last finished task when none is active", () => {
    const done = reduce(taskState(), { type: "envelope", envelope: env("task.result", { result: { status: "ok" } }, { task_id: "t-9" }), now: 0 });
    render(<DebugPanel state={done} storage={window.localStorage} />);

    expect(screen.getByText("t-9").closest("li")).toHaveTextContent("done");
  });

  it("shows the log path with a copy button and the reload list", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    expect(screen.getByText("logs/20261028/t-9.jsonl")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Copiar ruta" }));
    expect(writeText).toHaveBeenCalledWith("logs/20261028/t-9.jsonl");
    expect(screen.getByText("viernes").closest("li")).toHaveTextContent("filesystem, fetch");
  });

  it("copies the task tree as JSON and confirms it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    await userEvent.click(screen.getByRole("button", { name: "Copiar JSON" }));

    await waitFor(() => expect(screen.getByText("Copiado")).toBeInTheDocument());
    const exported = JSON.parse(String(writeText.mock.calls[0]?.[0])) as Record<string, unknown>;
    expect(exported).toMatchObject({ task_id: "t-9", status: "running" });
    expect(Object.keys(exported)).toEqual(expect.arrayContaining(["task_id", "status", "children", "tools", "usage"]));
    expect((exported.children as unknown[]).length).toBe(1);
    expect((exported.tools as unknown[]).length).toBe(3);
  });

  it("falls back to a textarea without clipboard", async () => {
    Object.assign(navigator, { clipboard: undefined });
    render(<DebugPanel state={taskState()} storage={window.localStorage} />);

    await userEvent.click(screen.getByRole("button", { name: "Copiar JSON" }));

    const area = screen.getByRole("textbox", { name: "JSON de la tarea" }) as HTMLTextAreaElement;
    expect(area.value).toContain('"task_id": "t-9"');
  });

  it("shows an empty state without tasks", () => {
    render(<DebugPanel state={initialState} storage={window.localStorage} />);

    expect(screen.getByText("Sin tareas delegadas todavía.")).toBeInTheDocument();
  });
});
