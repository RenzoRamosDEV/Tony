import type { Command, ReplyMode } from "../bridge/types";

const MODES: [ReplyMode, string][] = [
  ["auto", "Auto"],
  ["voice", "Voz"],
  ["text", "Texto"],
  ["both", "Voz y texto"],
];

interface Props {
  mode: ReplyMode;
  onCommand: (command: Command) => void;
}

export function ReplyModeSelector({ mode, onCommand }: Props) {
  return (
    <label className="reply-mode hud-corner holo">
      Respuesta{" "}
      <select
        aria-label="Modo de respuesta"
        value={mode}
        onChange={(event) => onCommand({ type: "set_mode", mode: event.target.value as ReplyMode })}
      >
        {MODES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );
}
