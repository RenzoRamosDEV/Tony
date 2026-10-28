import type { VoiceState } from "../protocol/types";
import { MicIcon } from "./icons";

export const INSTALL_HINT = "uv sync --extra voice";

interface Props {
  voice: VoiceState;
  onToggle: () => void;
}

export function MicButton({ voice, onToggle }: Props) {
  const on = voice.mic === "on";
  const unavailable = voice.available === false;
  const title = unavailable
    ? `Voz no disponible: ${voice.reason ?? "extra tony[voice] no instalado"}. Instala el extra con ${INSTALL_HINT}`
    : undefined;
  return (
    <button
      type="button"
      className={on ? "icon mic active" : "icon mic"}
      aria-pressed={on}
      aria-label={on ? "Desactivar micrófono" : "Activar micrófono"}
      disabled={unavailable}
      title={title}
      onClick={onToggle}
    >
      <MicIcon />
    </button>
  );
}
