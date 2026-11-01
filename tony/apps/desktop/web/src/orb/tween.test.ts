import { describe, expect, it } from "vitest";

import { approach, approachParams, MAX_DT_MS } from "./tween";
import type { OrbParams } from "./orbParams";

function params(value: number): OrbParams {
  return {
    spin: value,
    ringSpeed: value,
    coreScale: value,
    shellScale: value,
    displacement: value,
    agitation: value,
    bloom: value,
    glow: value,
    pulse: value,
  };
}

describe("approach", () => {
  it("stays put with dt 0", () => {
    expect(approach(2, 10, 0, 300)).toBe(2);
  });

  it("covers about 63 % of the gap after one time constant", () => {
    expect(approach(0, 1, 60, 60)).toBeCloseTo(1 - Math.exp(-1), 10);
  });

  it("moves downwards too", () => {
    expect(approach(1, 0, 60, 60)).toBeCloseTo(Math.exp(-1), 10);
  });

  it("clamps dt so a long pause does not jump", () => {
    expect(MAX_DT_MS).toBe(100);
    expect(approach(0, 1, 5000, 300)).toBeCloseTo(approach(0, 1, 100, 300), 10);
    expect(approach(0, 1, 100, 300)).toBeCloseTo(1 - Math.exp(-100 / 300), 10);
  });

  it("ignores negative dt", () => {
    expect(approach(3, 9, -50, 300)).toBe(3);
  });

  it("snaps to the target with a non-positive time constant", () => {
    expect(approach(3, 9, 16, 0)).toBe(9);
    expect(approach(3, 9, 16, -10)).toBe(9);
  });
});

describe("approachParams", () => {
  it("moves every field towards the target in place", () => {
    const current = params(0);

    const result = approachParams(current, params(1), 60, 60);

    expect(result).toBe(current);
    for (const value of Object.values(result)) {
      expect(value).toBeCloseTo(1 - Math.exp(-1), 10);
    }
  });

  it("an interruption starts from the current value, not from the old origin", () => {
    const current = params(0);
    approachParams(current, params(1), 150, 300);
    const midway = current.ringSpeed;

    approachParams(current, params(0), 16, 300);

    expect(current.ringSpeed).toBeLessThan(midway);
    expect(current.ringSpeed).toBeCloseTo(approach(midway, 0, 16, 300), 10);
  });
});
