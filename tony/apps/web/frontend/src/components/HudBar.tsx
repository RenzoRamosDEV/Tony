import type { ReplyMode, VoiceState } from "../protocol/types";
import { Composer } from "./Composer";
import { StopIcon } from "./icons";
import { MicButton } from "./MicButton";
import { ModeSelector } from "./ModeSelector";
import { StopAudioButton } from "./StopAudioButton";
import { VoiceStatus } from "./VoiceStatus";

export interface HudBarProps {
  voice: VoiceState;
  level: number;
  speaking: boolean;
  replyMode: ReplyMode;
  onModeChanged: (mode: ReplyMode) => void;
  fetchImpl?: typeof fetch;
  inputDisabled: boolean;
  onSend: (text: string) => boolean;
  onToggleMic: () => void;
  onStopAudio: () => void;
  canCancel: boolean;
  onCancel: () => void;
}

export function HudBar(props: HudBarProps) {
  const voice: VoiceState = props.speaking ? { ...props.voice, phase: "speaking" } : props.voice;
  return (
    <div role="group" aria-label="Controles de Jarvis" className="hud-bar hud-panel">
      <div className="hud-voice">
        <MicButton voice={props.voice} onToggle={props.onToggleMic} />
        <VoiceStatus voice={voice} level={props.level} />
        <StopAudioButton visible={props.speaking} onStop={props.onStopAudio} />
        {props.canCancel ? (
          <button type="button" className="secondary cancel" onClick={props.onCancel}>
            <StopIcon /> Cancelar tarea
          </button>
        ) : null}
      </div>
      <Composer disabled={props.inputDisabled} onSend={props.onSend} />
      <ModeSelector value={props.replyMode} onChanged={props.onModeChanged} fetchImpl={props.fetchImpl} />
    </div>
  );
}
