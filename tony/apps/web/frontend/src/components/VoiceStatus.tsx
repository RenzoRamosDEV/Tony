import type { VoicePhase, VoiceState } from "../protocol/types";

export const PHASE_TEXT: Record<VoicePhase, string | null> = {
  idle: null,
  listening: "Escuchando…",
  transcribing: "Transcribiendo…",
  speaking: "Hablando…",
};
/** RMS of 0.2 already fills the meter: speech levels are small numbers. */
const FULL_SCALE_RMS = 0.2;

interface Props {
  voice: VoiceState;
  level: number;
}

export function VoiceStatus({ voice, level }: Props) {
  const text = PHASE_TEXT[voice.phase];
  if (text === null && voice.mic === "off") {
    return null;
  }
  const percent = Math.round(Math.min(1, level / FULL_SCALE_RMS) * 100);
  return (
    <div className="voice-status">
      {text !== null ? (
        <p role="status" className="muted">
          {text}
        </p>
      ) : null}
      {voice.mic === "on" ? (
        <div
          className="level"
          role="meter"
          aria-label="Nivel de entrada"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <div className="level-bar" style={{ width: `${percent}%` }} />
        </div>
      ) : null}
    </div>
  );
}
