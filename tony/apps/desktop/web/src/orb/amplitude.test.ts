import { describe, expect, it } from "vitest";

import { AmplitudeSmoother, normalizeLevel } from "./amplitude";

describe("normalizeLevel", () => {
  // The core already sends levels normalised to [0, 1]: only clamping is left.
  it.each([
    [0, 0],
    [0.25, 0.25],
    [0.5, 0.5],
    [1, 1],
    [1.5, 1],
    [-0.1, 0],
  ])("normalizeLevel(%f) = %f", (input, expected) => {
    expect(normalizeLevel(input)).toBeCloseTo(expected, 10);
  });
});

describe("AmplitudeSmoother", () => {
  it("starts at 0", () => {
    expect(new AmplitudeSmoother().value).toBe(0);
  });

  it("attacks fast: 63 % after 40 ms", () => {
    const smoother = new AmplitudeSmoother();

    expect(smoother.update(1, 40)).toBeCloseTo(1 - Math.exp(-1), 6);
  });

  it("releases slowly: keeps 37 % after 180 ms", () => {
    const smoother = new AmplitudeSmoother();
    for (let i = 0; i < 100; i += 1) {
      smoother.update(1, 16);
    }

    smoother.update(0, 90);

    expect(smoother.update(0, 90)).toBeCloseTo(Math.exp(-1), 3);
  });

  it("does not depend on the frame rate", () => {
    const fast = new AmplitudeSmoother();
    const slow = new AmplitudeSmoother();
    fast.update(0.8, 10);
    fast.update(0.8, 10);
    fast.update(0.8, 10);
    slow.update(0.8, 30);

    expect(fast.value).toBeCloseTo(slow.value, 10);
  });

  it("keeps the value inside [0, 1]", () => {
    const smoother = new AmplitudeSmoother();
    for (let i = 0; i < 50; i += 1) {
      smoother.update(7, 50);
    }
    expect(smoother.value).toBeLessThanOrEqual(1);
    expect(smoother.value).toBeGreaterThan(0.99);
    for (let i = 0; i < 100; i += 1) {
      smoother.update(-3, 50);
    }
    expect(smoother.value).toBeGreaterThanOrEqual(0);
    expect(smoother.value).toBeLessThan(0.01);
  });

  it("reset returns to 0", () => {
    const smoother = new AmplitudeSmoother();
    smoother.update(1, 40);

    smoother.reset();

    expect(smoother.value).toBe(0);
  });
});
