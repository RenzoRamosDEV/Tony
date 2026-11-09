import { type ReactNode, useState } from "react";

import type { Command } from "../bridge/types";
import type { AudioDevicesView } from "../state/reducer";

const SYSTEM_DEFAULT_LABEL = "Sistema (predeterminado)";

interface Props {
  devices: AudioDevicesView;
  onCommand: (command: Command) => void;
  label?: string;
  children?: ReactNode;
}

interface DeviceSelectProps {
  id: string;
  label: string;
  kind: "input" | "output";
  options: { name: string; is_default: boolean }[];
  selected: string | null;
  warning: string | null;
  onCommand: (command: Command) => void;
}

function DeviceSelect({ id, label, kind, options, selected, warning, onCommand }: DeviceSelectProps) {
  return (
    <label htmlFor={id}>
      {label}
      <select
        id={id}
        value={selected ?? ""}
        onChange={(event) => {
          onCommand({ type: "set_audio_device", kind, device: event.target.value || null });
        }}
      >
        <option value="">{SYSTEM_DEFAULT_LABEL}</option>
        {options.map((option) => (
          <option key={option.name} value={option.name}>
            {option.name}
          </option>
        ))}
      </select>
      {warning !== null ? (
        <p className="warn" role="status">
          {warning}
        </p>
      ) : null}
    </label>
  );
}

export function AudioSettingsOverlay({ devices, onCommand, label = "Ajustes de audio", children }: Props) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        className="settings-trigger holo-frame holo"
        onClick={() => {
          setOpen(true);
          onCommand({ type: "list_devices" });
        }}
      >
        {label}
      </button>
    );
  }

  return (
    <div className="audio-settings-overlay">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="audio-settings-title"
        className="audio-settings-card holo-frame"
      >
        <h2 id="audio-settings-title" className="holo">
          {label}
        </h2>
        <DeviceSelect
          id="audio-input-device"
          label="Micrófono"
          kind="input"
          options={devices.input}
          selected={devices.selectedInput}
          warning={devices.inputWarning}
          onCommand={onCommand}
        />
        <DeviceSelect
          id="audio-output-device"
          label="Altavoz"
          kind="output"
          options={devices.output}
          selected={devices.selectedOutput}
          warning={devices.outputWarning}
          onCommand={onCommand}
        />
        {children}
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cerrar
        </button>
      </section>
    </div>
  );
}
