import { describe, expect, it } from "vitest";

import { drawAuroraOrb } from "./auroraOrb";
import type { OrbDrawing } from "./canvasScene";
import { drawDialOrb } from "./dialOrb";
import { fakeContext } from "./fakeContext";
import { emptyParams, targetParams } from "./orbParams";
import type { OrbState } from "./orbState";

const STATES: OrbState[] = ["idle", "listening", "thinking", "speaking", "confirming"];
const CLOCK = { t: 3.7, rot: 1.2, ring: 0.8, wobble: 2.1 };
const DRAWINGS: [string, OrbDrawing][] = [
  ["aurora", drawAuroraOrb],
  ["dial", drawDialOrb],
];

describe.each(DRAWINGS)("%s drawing", (_, draw) => {
  it.each(STATES)("paints finite coordinates for the %s state", (state) => {
    const fake = fakeContext();

    draw(fake.ctx, 800, 600, targetParams(state, 0.6, 0.6, false), CLOCK, 1);

    expect(fake.calls.length).toBeGreaterThan(10);
    expect(fake.numbers().every(Number.isFinite)).toBe(true);
  });

  it("survives a zero-sized stage and empty parameters", () => {
    const fake = fakeContext();

    draw(fake.ctx, 0, 0, emptyParams(), { t: 0, rot: 0, ring: 0, wobble: 0 }, 0.5);

    expect(fake.numbers().every(Number.isFinite)).toBe(true);
  });

  it("paints without conic gradients when the browser lacks them", () => {
    const fake = fakeContext({ conicGradient: false });

    expect(() => draw(fake.ctx, 800, 600, targetParams("thinking", 0, 0, false), CLOCK, 1)).not.toThrow();
    expect(fake.called("createConicGradient")).toBe(0);
  });

  it("looks different for reduced motion than for the same state with motion on the clock", () => {
    const moving = fakeContext();
    const still = fakeContext();

    draw(moving.ctx, 800, 600, targetParams("speaking", 0, 1, false), CLOCK, 1);
    draw(still.ctx, 800, 600, targetParams("speaking", 0, 1, true), CLOCK, 1);

    expect(JSON.stringify(moving.calls)).not.toBe(JSON.stringify(still.calls));
  });

  it("is brighter when glow rises", () => {
    const dim = fakeContext();
    const bright = fakeContext();

    draw(dim.ctx, 800, 600, { ...emptyParams(), glow: 0.2 }, CLOCK, 1);
    draw(bright.ctx, 800, 600, { ...emptyParams(), glow: 1.2 }, CLOCK, 1);

    expect(JSON.stringify(dim.calls)).not.toBe(JSON.stringify(bright.calls));
  });
});

describe("aurora drawing", () => {
  it("uses a clipped liquid drop with a conic gradient", () => {
    const fake = fakeContext();
    drawAuroraOrb(fake.ctx, 800, 600, emptyParams(), CLOCK, 1);
    expect(fake.called("clip")).toBe(1);
    expect(fake.called("createConicGradient")).toBe(1);
  });
});

describe("dial drawing", () => {
  it("draws 120 ticks and 96 level bars", () => {
    const fake = fakeContext();
    drawDialOrb(fake.ctx, 800, 600, emptyParams(), CLOCK, 1);
    expect(fake.called("stroke")).toBeGreaterThanOrEqual(120 + 96);
  });
});

describe("aurora motion smoothness", () => {
  const WIDTH = 1000;
  const LONG_RUNNING_CLOCK = { t: 600, rot: 130, ring: 480, wobble: 420 };

  function outline(params: ReturnType<typeof emptyParams>, clock = LONG_RUNNING_CLOCK) {
    const fake = fakeContext();
    drawAuroraOrb(fake.ctx, WIDTH, WIDTH, params, clock, 1);
    return fake.calls
      .filter((call) => call.method === "moveTo" || call.method === "lineTo")
      .slice(0, 97)
      .map((call) => call.args as [number, number]);
  }

  function maxDistance(a: [number, number][], b: [number, number][]) {
    return Math.max(...a.map(([x, y], i) => Math.hypot(x - b[i]![0], y - b[i]![1])));
  }

  function radialDeviation(params: ReturnType<typeof emptyParams>) {
    const radius = WIDTH * 0.28 * params.shellScale;
    return Math.max(...outline(params).map(([x, y]) => Math.abs(Math.hypot(x - WIDTH / 2, y - WIDTH / 2) / radius - 1)));
  }

  it("does not jump the outline when only the agitation changes late in a long session", () => {
    const base = { ...emptyParams(), displacement: 0.1, shellScale: 1 };

    const calm = outline({ ...base, agitation: 0.1 });
    const excited = outline({ ...base, agitation: 0.6 });

    expect(maxDistance(calm, excited)).toBeLessThan(0.5);
  });

  it("moves the outline smoothly as the wobble phase advances one frame", () => {
    const params = { ...emptyParams(), displacement: 0.18, agitation: 0.6 };

    const before = outline(params);
    const after = outline(params, { ...LONG_RUNNING_CLOCK, wobble: LONG_RUNNING_CLOCK.wobble + 0.02 });

    expect(maxDistance(before, after)).toBeLessThan(2);
  });

  it("deforms at full voice at most twice as much as at rest", () => {
    const rest = radialDeviation(targetParams("idle", 0, 0, false));
    const loud = radialDeviation(targetParams("speaking", 0, 1, false));

    expect(loud / rest).toBeLessThanOrEqual(2);
  });

  it("spins the conic gradient no faster than the orb itself", () => {
    const angleAt = (rot: number) => {
      const fake = fakeContext();
      drawAuroraOrb(fake.ctx, WIDTH, WIDTH, emptyParams(), { ...LONG_RUNNING_CLOCK, rot }, 1);
      return fake.calls.find((call) => call.method === "createConicGradient")!.args[0] as number;
    };

    expect(Math.abs(angleAt(1) - angleAt(0))).toBeLessThanOrEqual(1);
  });

  it("moves the outline only slowly when the clock time advances with a fixed wobble phase", () => {
    const params = { ...emptyParams(), displacement: 0.18 };

    const before = outline(params);
    const after = outline(params, { ...LONG_RUNNING_CLOCK, t: LONG_RUNNING_CLOCK.t + 0.1 });

    expect(maxDistance(before, after)).toBeLessThan(0.6);
  });

  it("orbits the colour blobs no faster than 1.2 times the rotation", () => {
    const blobAngles = (rot: number) => {
      const fake = fakeContext();
      drawAuroraOrb(fake.ctx, WIDTH, WIDTH, emptyParams(), { ...LONG_RUNNING_CLOCK, rot }, 1);
      return fake.calls
        .filter((call) => call.method === "createRadialGradient" && call.args[5] === WIDTH * 0.28 * 0.8)
        .map((call) => Math.atan2((call.args[1] as number) - WIDTH / 2, (call.args[0] as number) - WIDTH / 2));
    };
    const rotationStep = 0.1;

    const before = blobAngles(1);
    const after = blobAngles(1 + rotationStep);

    expect(before).toHaveLength(4);
    before.forEach((angle, k) => {
      const travelled = Math.abs(Math.atan2(Math.sin(after[k]! - angle), Math.cos(after[k]! - angle)));
      expect(travelled).toBeGreaterThan(0);
      expect(travelled).toBeLessThanOrEqual(1.2 * rotationStep);
    });
  });
});
