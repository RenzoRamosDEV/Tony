import { afterEach, describe, expect, it, vi } from "vitest";

import { connectBridge } from "./channel";
import type { CoreEvent } from "./types";

class FakeSignal<T extends unknown[]> {
  private handlers: ((...args: T) => void)[] = [];
  connect(handler: (...args: T) => void) {
    this.handlers.push(handler);
  }
  emit(...args: T) {
    for (const handler of this.handlers) handler(...args);
  }
}

function fakeTony() {
  return {
    event: new FakeSignal<[string]>(),
    focusConfirmation: new FakeSignal<[]>(),
    sent: [] as string[],
    readyCalls: 0,
    auditRows: "[]",
    send(text: string) {
      this.sent.push(text);
    },
    ready() {
      this.readyCalls += 1;
    },
    auditToday(callback: (result: string) => void) {
      callback(this.auditRows);
    },
  };
}

function install(tony: ReturnType<typeof fakeTony>) {
  const transport = { name: "transport" };
  const created: unknown[] = [];
  vi.stubGlobal("qt", { webChannelTransport: transport });
  vi.stubGlobal(
    "QWebChannel",
    class {
      constructor(given: unknown, ready: (channel: { objects: { tony: unknown } }) => void) {
        created.push(given);
        ready({ objects: { tony } });
      }
    },
  );
  return { transport, created };
}

const TOKEN: CoreEvent = { type: "token", ts: "t", agent: "jarvis", text: "Hola" };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("connectBridge", () => {
  it("opens the channel on Qt's transport", async () => {
    const { transport, created } = install(fakeTony());

    await connectBridge();

    expect(created).toEqual([transport]);
  });

  it("parses each event's JSON for the handler", async () => {
    const tony = fakeTony();
    install(tony);
    const bridge = await connectBridge();
    const received: CoreEvent[] = [];

    bridge.onEvent((event) => received.push(event));
    tony.event.emit(JSON.stringify(TOKEN));

    expect(received).toEqual([TOKEN]);
  });

  it("ignores malformed event JSON", async () => {
    const tony = fakeTony();
    install(tony);
    const bridge = await connectBridge();
    const received: CoreEvent[] = [];
    bridge.onEvent((event) => received.push(event));

    tony.event.emit("{nope");
    tony.event.emit(JSON.stringify(TOKEN));

    expect(received).toEqual([TOKEN]);
  });

  it("announces ready once, only after the event handler is attached", async () => {
    const tony = fakeTony();
    install(tony);
    const bridge = await connectBridge();

    expect(tony.readyCalls).toBe(0);
    bridge.onEvent(() => undefined);
    bridge.onEvent(() => undefined);

    expect(tony.readyCalls).toBe(1);
  });

  it("sends commands as JSON text", async () => {
    const tony = fakeTony();
    install(tony);
    const bridge = await connectBridge();

    bridge.send({ type: "confirm", task_id: "t1", decision: "allow" });

    expect(tony.sent).toEqual(['{"type":"confirm","task_id":"t1","decision":"allow"}']);
  });

  it("parses today's audit rows", async () => {
    const tony = fakeTony();
    const row = { time: "10:00:00", agent: "viernes", tool: "shell.run", verdict: "deny", rule: "r", user_decision: null };
    tony.auditRows = JSON.stringify([row]);
    install(tony);
    const bridge = await connectBridge();

    await expect(bridge.auditToday()).resolves.toEqual([row]);
  });

  it("treats a malformed audit answer as no rows", async () => {
    const tony = fakeTony();
    tony.auditRows = "oops";
    install(tony);
    const bridge = await connectBridge();

    await expect(bridge.auditToday()).resolves.toEqual([]);
  });

  it("forwards focus requests", async () => {
    const tony = fakeTony();
    install(tony);
    const bridge = await connectBridge();
    const focus = vi.fn();

    bridge.onFocusConfirmation(focus);
    tony.focusConfirmation.emit();

    expect(focus).toHaveBeenCalledTimes(1);
  });

  it("rejects when the page is not inside the desktop window", async () => {
    await expect(connectBridge()).rejects.toThrow(/QWebChannel/);
  });
});
