import type { VoicePhase, VoiceState } from "../protocol/types";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export interface OrbStateInputs {
  phase: VoicePhase;
  mic: VoiceState["mic"];
  playing: boolean;
  turnInProgress: boolean;
  activeRootId: string | null;
}

export function deriveOrbState(inputs: OrbStateInputs): OrbState {
  if (inputs.phase === "speaking" || inputs.playing) {
    return "speaking";
  }
  if (inputs.turnInProgress || inputs.activeRootId !== null || inputs.phase === "transcribing") {
    return "thinking";
  }
  return inputs.mic === "on" ? "listening" : "idle";
}
