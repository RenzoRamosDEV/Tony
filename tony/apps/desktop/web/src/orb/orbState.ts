import type { VoiceStateName } from "../bridge/types";

export type OrbState = "idle" | "listening" | "thinking" | "speaking" | "confirming";

/** Without a new output level for this long, speech is over. */
export const SPEAKING_HOLD_MS = 300;

export interface OrbStateInputs {
  confirming: boolean;
  /** Epoch milliseconds of the latest `voice_level` with source `output`. */
  lastOutputAt: number | null;
  voice: VoiceStateName;
  thinking: boolean;
}

export function deriveOrbState(inputs: OrbStateInputs, now: number): OrbState {
  if (inputs.confirming) {
    return "confirming";
  }
  if (inputs.lastOutputAt !== null && now - inputs.lastOutputAt < SPEAKING_HOLD_MS) {
    return "speaking";
  }
  if (inputs.voice === "listening") {
    return "listening";
  }
  return inputs.thinking ? "thinking" : "idle";
}
