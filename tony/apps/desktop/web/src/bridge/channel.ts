import type { AuditRow, Command, CoreEvent, ResizeEdge, TonyBridge } from "./types";

interface QtSignal<T extends unknown[]> {
  connect(handler: (...args: T) => void): void;
}

/** The `tony` object Python registers on the QWebChannel (tony/apps/desktop/page_bridge.py). */
interface ChannelObject {
  event: QtSignal<[string]>;
  focusConfirmation: QtSignal<[]>;
  send(text: string): void;
  ready(): void;
  auditToday(callback: (result: string) => void): void;
}

/** The `windowControls` object Python registers, if any (tony/apps/desktop/window_controls.py). */
interface WindowChannelObject {
  minimize(): void;
  toggleMaximize(): void;
  close(): void;
  startMove(): void;
  startResize(edge: string): void;
}

interface QWebChannelConstructor {
  new (
    transport: unknown,
    ready: (channel: { objects: { tony: ChannelObject; windowControls?: WindowChannelObject } }) => void,
  ): unknown;
}

declare global {
  // Injected by the desktop window before the page's own scripts run.
  var QWebChannel: QWebChannelConstructor | undefined;
  var qt: { webChannelTransport: unknown } | undefined;
}

function parse<T>(text: string): T | undefined {
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined;
  }
}

function wrapWindow(controls: WindowChannelObject): TonyBridge["window"] {
  return {
    minimize: () => controls.minimize(),
    toggleMaximize: () => controls.toggleMaximize(),
    close: () => controls.close(),
    startMove: () => controls.startMove(),
    startResize: (edge: ResizeEdge) => controls.startResize(edge),
  };
}

function wrap(tony: ChannelObject, windowControls: WindowChannelObject | undefined): TonyBridge {
  let announced = false;
  return {
    onEvent(handler) {
      tony.event.connect((text) => {
        const event = parse<CoreEvent>(text);
        if (event !== undefined) {
          handler(event);
        }
      });
      if (!announced) {
        announced = true;
        tony.ready();
      }
    },
    onFocusConfirmation(handler) {
      tony.focusConfirmation.connect(handler);
    },
    send(command: Command) {
      tony.send(JSON.stringify(command));
    },
    auditToday() {
      return new Promise<AuditRow[]>((resolve) => {
        tony.auditToday((result) => {
          const rows = parse<AuditRow[]>(result);
          resolve(Array.isArray(rows) ? rows : []);
        });
      });
    },
    window: windowControls ? wrapWindow(windowControls) : null,
  };
}

export function connectBridge(): Promise<TonyBridge> {
  const Channel = globalThis.QWebChannel;
  const transport = globalThis.qt?.webChannelTransport;
  if (Channel === undefined || transport === undefined) {
    return Promise.reject(new Error("QWebChannel is not available outside the desktop window"));
  }
  return new Promise((resolve) => {
    new Channel(transport, (channel) => resolve(wrap(channel.objects.tony, channel.objects.windowControls)));
  });
}
