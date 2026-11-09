export interface Call {
  method: string;
  args: unknown[];
}

export interface FakeContext {
  ctx: CanvasRenderingContext2D;
  calls: Call[];
  numbers: () => number[];
  called: (method: string) => number;
}

interface Options {
  conicGradient?: boolean;
}

/** Records every drawing call and answers gradients with an object that accepts colour stops. */
export function fakeContext({ conicGradient = true }: Options = {}): FakeContext {
  const calls: Call[] = [];
  const gradient = () => ({ addColorStop: (...args: unknown[]) => calls.push({ method: "addColorStop", args }) });
  const target: Record<string, unknown> = {};
  const ctx = new Proxy(target, {
    get(_, name: string) {
      if (name === "createConicGradient" && !conicGradient) {
        return undefined;
      }
      if (name in target) {
        return target[name];
      }
      return (...args: unknown[]) => {
        calls.push({ method: name, args });
        return name.startsWith("create") ? gradient() : undefined;
      };
    },
    set(_, name: string, value: unknown) {
      target[name] = value;
      calls.push({ method: `set:${name}`, args: [value] });
      return true;
    },
  }) as unknown as CanvasRenderingContext2D;
  return {
    ctx,
    calls,
    numbers: () => calls.flatMap((call) => call.args).filter((arg): arg is number => typeof arg === "number"),
    called: (method) => calls.filter((call) => call.method === method).length,
  };
}
