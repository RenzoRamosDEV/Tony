import { describe, expect, it } from "vitest";

import { deriveOrbState, type OrbStateInputs } from "./orbState";

const REST: OrbStateInputs = { phase: "idle", mic: "off", playing: false, turnInProgress: false, activeRootId: null };

describe("deriveOrbState", () => {
  it.each<[string, Partial<OrbStateInputs>, string]>([
    ["nothing happening", {}, "idle"],
    ["microphone on", { mic: "on", phase: "listening" }, "listening"],
    ["microphone on without phase", { mic: "on" }, "listening"],
    ["turn in progress", { turnInProgress: true }, "thinking"],
    ["task running without a turn", { activeRootId: "t-9" }, "thinking"],
    ["transcribing", { mic: "on", phase: "transcribing" }, "thinking"],
    ["thinking beats listening", { mic: "on", turnInProgress: true }, "thinking"],
    ["synthesizing", { phase: "speaking" }, "speaking"],
    ["playing without a phase", { playing: true }, "speaking"],
    [
      "speaking beats everything",
      { mic: "on", playing: true, turnInProgress: true, activeRootId: "t-9", phase: "transcribing" },
      "speaking",
    ],
  ])("%s -> %s", (_name, overrides, expected) => {
    expect(deriveOrbState({ ...REST, ...overrides })).toBe(expected);
  });
});
