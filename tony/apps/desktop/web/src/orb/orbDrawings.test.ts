import { describe, expect, it } from "vitest";

import { drawAuroraOrb } from "./auroraOrb";
import type { OrbDrawing } from "./canvasScene";
import { drawDialOrb } from "./dialOrb";
import { fakeContext } from "./fakeContext";
import { emptyParams, targetParams } from "./orbParams";
import type { OrbState } from "./orbState";

const STATES: OrbState[] = ["idle", "listening", "thinking", "speaking", "confirming"];
const CLOCK = { t: 3.7, rot: 1.2, ring: 0.8 };
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

    draw(fake.ctx, 0, 0, emptyParams(), { t: 0, rot: 0, ring: 0 }, 0.5);

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
