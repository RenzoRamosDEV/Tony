import { StopIcon } from "./icons";

interface Props {
  visible: boolean;
  onStop: () => void;
}

export function StopAudioButton({ visible, onStop }: Props) {
  if (!visible) {
    return null;
  }
  return (
    <button type="button" className="secondary stop-audio" aria-label="Detener audio" onClick={onStop}>
      <StopIcon /> Detener audio
    </button>
  );
}
