import { describe, expect, it } from "vitest";

import { deriveOrbState, type OrbStateInputs, SPEAKING_HOLD_MS } from "./orbState";

const NOW = 10_000;
const IDLE: OrbStateInputs = { confirming: false, lastOutputAt: null, voice: "ready", thinking: false };

function at(inputs: Partial<OrbStateInputs>, now = NOW) {
  return deriveOrbState({ ...IDLE, ...inputs }, now);
}

describe("deriveOrbState", () => {
  it("is idle with nothing going on", () => {
    expect(at({})).toBe("idle");
  });

  it.each(["loading", "unavailable", "ready"] as const)("is idle while voice is %s", (voice) => {
    expect(at({ voice })).toBe("idle");
  });

  it("is listening while voice is listening", () => {
    expect(at({ voice: "listening" })).toBe("listening");
  });

  it("is thinking while a turn or task is being worked on", () => {
    expect(at({ thinking: true })).toBe("thinking");
  });

  it("holds speaking for 300 ms after the last output level", () => {
    expect(SPEAKING_HOLD_MS).toBe(300);
    expect(at({ lastOutputAt: NOW })).toBe("speaking");
    expect(at({ lastOutputAt: NOW - 299 })).toBe("speaking");
    expect(at({ lastOutputAt: NOW - 300 })).toBe("idle");
    expect(at({ lastOutputAt: NOW - 301, thinking: true })).toBe("thinking");
  });

  it("listening wins over thinking", () => {
    expect(at({ voice: "listening", thinking: true })).toBe("listening");
  });

  it("speaking wins over listening and thinking", () => {
    expect(at({ voice: "listening", thinking: true, lastOutputAt: NOW })).toBe("speaking");
  });

  it("confirming wins over everything", () => {
    expect(at({ confirming: true, voice: "listening", thinking: true, lastOutputAt: NOW })).toBe("confirming");
  });
});
