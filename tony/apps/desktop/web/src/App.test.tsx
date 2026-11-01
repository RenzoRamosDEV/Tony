import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuditRow, Command, CoreEvent, TonyBridge } from "./bridge/types";
import type { OrbParams } from "./orb/orbParams";
import type { OrbScene } from "./orb/scene";

const chatRenders = vi.hoisted(() => ({ count: 0 }));

vi.mock("./components/ChatPanel", async (importOriginal) => {
  const original = await importOriginal<typeof import("./components/ChatPanel")>();
  return {
    ChatPanel: (props: Parameters<typeof original.ChatPanel>[0]) => {
      chatRenders.count += 1;
      return original.ChatPanel(props);
    },
  };
});

const TS = "2026-11-01T10:00:00+00:00";
const ROW: AuditRow = { time: "09:00:00", agent: "viernes", tool: "shell.run", verdict: "deny", rule: "r", user_decision: null };

class FakeBridge implements TonyBridge {
  handlers: ((event: CoreEvent) => void)[] = [];
  focusHandlers: (() => void)[] = [];
  sent: Command[] = [];
  auditCalls = 0;

  onEvent(handler: (event: CoreEvent) => void) {
    this.handlers.push(handler);
  }
  onFocusConfirmation(handler: () => void) {
    this.focusHandlers.push(handler);
  }
  send(command: Command) {
    this.sent.push(command);
  }
  auditToday() {
    this.auditCalls += 1;
    return Promise.resolve([ROW]);
  }
  emit(...events: CoreEvent[]) {
    act(() => {
      for (const event of events) {
        this.handlers.forEach((handler) => handler(event));
      }
    });
  }
}

class FakeScene implements OrbScene {
  last: OrbParams | null = null;
  update(params: OrbParams): void {
    this.last = { ...params };
  }
  resize(): void {}
  setAutoRotate(): void {}
  onInteraction(): () => void {
    return () => undefined;
  }
  dispose(): void {}
}

async function mount(options: { webgl?: boolean; scene?: FakeScene } = {}) {
  const bridge = new FakeBridge();
  const scene = options.scene ?? new FakeScene();
  render(
    <App
      connect={() => Promise.resolve(bridge)}
      createScene={() => scene}
      webglAvailable={() => options.webgl ?? false}
    />,
  );
  await act(async () => {
    await Promise.resolve();
  });
  return { bridge, scene };
}

const stage = () => document.querySelector(".stage") as HTMLElement;
const turnStarted = (writes: boolean): CoreEvent => ({
  type: "turn_started", ts: TS, agent: "jarvis", origin: "voice", reply_mode: "auto", speaks: !writes, writes,
});
const level = (source: "input" | "output", value: number): CoreEvent => ({ type: "voice_level", ts: TS, source, level: value });
const voice = (state: "ready" | "listening"): CoreEvent => ({ type: "voice_state", ts: TS, state, reason: null });

beforeEach(() => {
  chatRenders.count = 0;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("lays out the orb, chat, microphone, reply mode and both panels", async () => {
    await mount();

    expect(stage()).not.toBeNull();
    expect(screen.getByRole("region", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Mensaje" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Micrófono" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Modo de respuesta" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actividad/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Edith/ })).toHaveAttribute("aria-expanded", "true");
  });

  it("loads today's audit once after connecting", async () => {
    const { bridge } = await mount();

    expect(bridge.auditCalls).toBe(1);
    expect(screen.getByText("shell.run")).toBeInTheDocument();
  });

  it("listens to the bridge once", async () => {
    const { bridge } = await mount();

    expect(bridge.handlers).toHaveLength(1);
  });

  it("events drive the components", async () => {
    const { bridge } = await mount();

    bridge.emit(
      { type: "reply_mode", ts: TS, mode: "both" },
      voice("ready"),
      { type: "token", ts: TS, agent: "jarvis", text: "Buenas tardes" },
      { type: "task_started", ts: TS, task_id: "t1", agent: "viernes", objetivo: "leer notas" },
    );

    expect(screen.getByRole("combobox", { name: "Modo de respuesta" })).toHaveValue("both");
    expect(screen.getByRole("button", { name: "Micrófono" })).toBeEnabled();
    expect(screen.getByText("Buenas tardes")).toBeInTheDocument();
    expect(screen.getByText("viernes: leer notas")).toBeInTheDocument();
  });

  it("sends typed messages and shows them", async () => {
    const { bridge } = await mount();

    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje" }), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(bridge.sent).toEqual([{ type: "send_message", text: "Hola" }]);
    expect(screen.getByText("Hola")).toBeInTheDocument();
  });

  it("voice levels do not re-render the chat", async () => {
    const { bridge } = await mount();
    bridge.emit(voice("listening"));
    const before = chatRenders.count;

    bridge.emit(level("input", 0.2), level("input", 0.8), level("input", 0.5));

    expect(chatRenders.count).toBe(before);
  });

  it("input levels drive the orb amplitude while listening and decay after", async () => {
    let clock = 0;
    let frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    const step = (count: number) => {
      for (let i = 0; i < count; i += 1) {
        clock += 16;
        const pending = frames;
        frames = [];
        act(() => pending.forEach((callback) => callback(clock)));
      }
    };
    const { bridge, scene } = await mount({ webgl: true });
    bridge.emit(voice("listening"));
    step(10);
    const quiet = scene.last?.coreScale ?? 0;

    vi.useFakeTimers({ toFake: ["Date"] });
    bridge.emit(level("input", 0.8));
    step(40);
    const loud = scene.last?.coreScale ?? 0;
    vi.advanceTimersByTime(1000);
    step(80);

    expect(quiet).toBeCloseTo(1, 3);
    expect(loud).toBeGreaterThan(1.25);
    expect(scene.last?.coreScale).toBeCloseTo(1, 2);
  });

  it("the orb goes thinking, speaking and back to idle 300 ms after the last output level", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    const { bridge } = await mount();
    expect(stage()).toHaveAttribute("data-orb-state", "idle");

    bridge.emit(turnStarted(false), { type: "token", ts: TS, agent: "jarvis", text: "Ho" });
    expect(stage()).toHaveAttribute("data-orb-state", "thinking");

    bridge.emit(level("output", 0.5));
    expect(stage()).toHaveAttribute("data-orb-state", "speaking");

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(stage()).toHaveAttribute("data-orb-state", "speaking");

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(stage()).toHaveAttribute("data-orb-state", "idle");
  });

  it("answering the confirmation sends the command and leaves confirming", async () => {
    const { bridge } = await mount();
    bridge.emit({
      type: "needs_confirmation", ts: TS, task_id: "t1", tool: "filesystem.delete_file",
      args_preview: "{}", question: "¿Borrar?", allow_always: true,
    });
    expect(stage()).toHaveAttribute("data-orb-state", "confirming");
    expect(screen.getByRole("button", { name: "Denegar" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Permitir" }));

    expect(bridge.sent).toEqual([{ type: "confirm", task_id: "t1", decision: "allow" }]);
    expect(screen.queryByRole("button", { name: "Permitir" })).toBeNull();
    expect(stage()).toHaveAttribute("data-orb-state", "idle");
  });

  it("a focus request puts the focus back on «Denegar»", async () => {
    const { bridge } = await mount();
    bridge.emit({
      type: "needs_confirmation", ts: TS, task_id: "t1", tool: "x", args_preview: "{}", question: "?", allow_always: false,
    });
    screen.getByRole("textbox", { name: "Mensaje" }).focus();

    act(() => bridge.focusHandlers.forEach((handler) => handler()));

    expect(screen.getByRole("button", { name: "Denegar" })).toHaveFocus();
  });

  it("without WebGL shows the fallback orb and the chat still sends", async () => {
    const { bridge } = await mount({ webgl: false });

    expect(document.querySelector(".orb-fallback")).not.toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Mensaje" }), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(bridge.sent).toEqual([{ type: "send_message", text: "Hola" }]);
  });

  it("shows a page error when the bridge is not available", async () => {
    render(<App connect={() => Promise.reject(new Error("no QWebChannel"))} webglAvailable={() => false} />);
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText(/no QWebChannel/)).toBeInTheDocument();
  });
});
