import type { Command } from "../bridge/types";
import { micView, type UiState } from "../state/reducer";

interface Props {
  voice: UiState["voice"];
  onCommand: (command: Command) => void;
}

export function MicButton({ voice, onCommand }: Props) {
  const view = micView(voice);
  const toggle = () => onCommand(voice.state === "listening" ? { type: "stop_listening" } : { type: "listen" });
  return (
    <button
      type="button"
      className="mic-toggle holo-frame holo"
      data-voice-state={voice.state}
      disabled={!view.enabled}
      title={view.tooltip}
      onClick={toggle}
    >
      {view.label}
    </button>
  );
}
