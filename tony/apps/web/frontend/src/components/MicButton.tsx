import type { VoicePhase, VoiceState } from "../protocol/types";

interface Props {
  mic: VoiceState["mic"];
  phase: VoicePhase;
  available: boolean | null;
  onToggle: () => void;
}

export function MicButton({ mic, phase, available, onToggle }: Props) {
  return (
    <button
      type="button"
      className="mic-toggle holo"
      data-mic-state={mic}
      data-voice-phase={phase}
      disabled={available === false}
      onClick={onToggle}
    >
      Micrófono
    </button>
  );
}
