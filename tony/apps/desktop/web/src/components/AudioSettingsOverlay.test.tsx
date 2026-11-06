import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AudioDevicesView } from "../state/reducer";
import { AudioSettingsOverlay } from "./AudioSettingsOverlay";

const emptyDevices: AudioDevicesView = {
  input: [],
  output: [],
  selectedInput: null,
  selectedOutput: null,
  inputWarning: null,
  outputWarning: null,
};

describe("AudioSettingsOverlay", () => {
  it("clicking the gear trigger opens the overlay and requests the device list", () => {
    const onCommand = vi.fn();
    render(<AudioSettingsOverlay devices={emptyDevices} onCommand={onCommand} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
    expect(onCommand).toHaveBeenCalledWith({ type: "list_devices" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("selecting an input device sends set_audio_device", () => {
    const onCommand = vi.fn();
    const devices = { ...emptyDevices, input: [{ name: "Mic A", is_default: true }] };
    render(<AudioSettingsOverlay devices={devices} onCommand={onCommand} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
    fireEvent.change(screen.getByLabelText(/micrófono/i), { target: { value: "Mic A" } });
    expect(onCommand).toHaveBeenCalledWith({ type: "set_audio_device", kind: "input", device: "Mic A" });
  });

  it("choosing system default sends a null device", () => {
    const onCommand = vi.fn();
    render(<AudioSettingsOverlay devices={emptyDevices} onCommand={onCommand} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
    fireEvent.change(screen.getByLabelText(/micrófono/i), { target: { value: "" } });
    expect(onCommand).toHaveBeenCalledWith({ type: "set_audio_device", kind: "input", device: null });
  });

  it("shows the input fallback warning when present", () => {
    const devices = { ...emptyDevices, inputWarning: "Dispositivo 'X' no disponible; usando predeterminado." };
    render(<AudioSettingsOverlay devices={devices} onCommand={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
    expect(screen.getByText(/no disponible/i)).toBeInTheDocument();
  });
});
