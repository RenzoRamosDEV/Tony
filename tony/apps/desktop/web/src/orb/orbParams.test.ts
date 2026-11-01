import { describe, expect, it } from "vitest";

import { emptyParams, MAX_CORE_SCALE, MAX_SHELL_SCALE, type OrbParams, targetParams } from "./orbParams";

describe("targetParams", () => {
  it("idle rotates slowly with a gentle breathing glow", () => {
    const idle = targetParams("idle", 0, 0, false);

    expect(idle.spin).toBeGreaterThan(0);
    expect(idle.pulse).toBeGreaterThan(0);
    expect(idle.coreScale).toBe(1);
    expect(idle.shellScale).toBe(1);
  });

  it("thinking spins the arcs faster and pulses harder than idle", () => {
    const idle = targetParams("idle", 0, 0, false);
    const thinking = targetParams("thinking", 0, 0, false);

    expect(thinking.ringSpeed).toBeGreaterThan(idle.ringSpeed * 3);
    expect(thinking.pulse).toBeGreaterThan(idle.pulse * 2);
    expect(thinking.spin).toBeGreaterThan(idle.spin);
  });

  it("listening at level 0 holds its pose without agitation", () => {
    const listening = targetParams("listening", 0, 0, false);

    expect(listening.agitation).toBe(0);
    expect(listening.coreScale).toBe(1);
    expect(listening.shellScale).toBe(1);
  });

  it("listening grows and agitates with the microphone level", () => {
    const quiet = targetParams("listening", 0, 0, false);
    const loud = targetParams("listening", 0.5, 0, false);
    const full = targetParams("listening", 1, 0, false);

    expect(loud.coreScale).toBeGreaterThan(quiet.coreScale);
    expect(full.coreScale).toBeGreaterThan(loud.coreScale);
    expect(full.shellScale).toBeGreaterThan(quiet.shellScale);
    expect(full.agitation).toBeGreaterThan(loud.agitation);
    expect(full.coreScale).toBeCloseTo(MAX_CORE_SCALE, 10);
    expect(full.shellScale).toBeCloseTo(MAX_SHELL_SCALE, 10);
  });

  it("a level above full scale never exceeds the maximum scale", () => {
    const over = targetParams("listening", 5, 0, false);
    const full = targetParams("listening", 1, 0, false);

    expect(over).toEqual(full);
  });

  it("speaking follows the playback amplitude", () => {
    const silent = targetParams("speaking", 0, 0, false);
    const loud = targetParams("speaking", 0, 1, false);

    expect(loud.displacement).toBeGreaterThan(silent.displacement);
    expect(loud.ringSpeed).toBeGreaterThan(silent.ringSpeed);
    expect(loud.glow).toBeGreaterThan(silent.glow);
    expect(loud.bloom).toBeGreaterThan(silent.bloom);
    expect(loud.coreScale).toBeCloseTo(MAX_CORE_SCALE, 10);
    expect(loud.shellScale).toBeCloseTo(MAX_SHELL_SCALE, 10);
    expect(silent.coreScale).toBe(1);
  });

  it("clamps the amplitude to [0, 1]", () => {
    expect(targetParams("speaking", 0, 3, false)).toEqual(targetParams("speaking", 0, 1, false));
    expect(targetParams("speaking", 0, -1, false)).toEqual(targetParams("speaking", 0, 0, false));
  });

  it("ignores the microphone level outside listening", () => {
    expect(targetParams("idle", 1, 0, false)).toEqual(targetParams("idle", 0, 0, false));
    expect(targetParams("thinking", 0, 1, false)).toEqual(targetParams("thinking", 0, 0, false));
  });

  it.each(["idle", "listening", "thinking", "speaking"] as const)(
    "reduced motion freezes %s and only changes brightness",
    (state) => {
      const reduced = targetParams(state, 0.2, 1, true);
      const normal = targetParams(state, 0.2, 1, false);

      expect(reduced.spin).toBe(0);
      expect(reduced.ringSpeed).toBe(0);
      expect(reduced.displacement).toBe(0);
      expect(reduced.agitation).toBe(0);
      expect(reduced.pulse).toBe(0);
      expect(reduced.coreScale).toBe(1);
      expect(reduced.shellScale).toBe(1);
      expect(reduced.glow).toBe(normal.glow);
      expect(reduced.bloom).toBe(normal.bloom);
    },
  );

  it("reduced motion still tells the states apart by brightness", () => {
    expect(targetParams("thinking", 0, 0, true).glow).not.toBe(targetParams("idle", 0, 0, true).glow);
  });

  it("writes into the given object to avoid per-frame allocations", () => {
    const out = targetParams("idle", 0, 0, false);

    const result = targetParams("thinking", 0, 0, false, out);

    expect(result).toBe(out);
    expect(out).toEqual(targetParams("thinking", 0, 0, false));
  });

  it.each([
    ["listening", (x: number) => targetParams("listening", x, 0, false)],
    ["speaking", (x: number) => targetParams("speaking", 0, x, false)],
  ] as const)("%s responds linearly to its input", (_state, at) => {
    const low = at(0);
    const mid = at(0.5);
    const high = at(1);
    for (const key of Object.keys(mid) as (keyof OrbParams)[]) {
      expect(mid[key], key).toBeCloseTo((low[key] + high[key]) / 2, 10);
    }
    expect(high.displacement).toBeGreaterThan(low.displacement);
    expect(high.agitation).toBeGreaterThan(low.agitation);
    expect(high.bloom).toBeGreaterThan(low.bloom);
    expect(high.glow).toBeGreaterThan(low.glow);
  });

  it("starts from a neutral, motionless set of params", () => {
    expect(emptyParams()).toEqual({
      spin: 0, ringSpeed: 0, coreScale: 1, shellScale: 1, displacement: 0, agitation: 0, bloom: 0, glow: 0, pulse: 0,
    });
  });
});
