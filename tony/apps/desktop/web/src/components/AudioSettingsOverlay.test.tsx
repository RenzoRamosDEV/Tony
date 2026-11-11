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

  it("keeps the audio label by default and accepts a custom one", () => {
    const { rerender } = render(<AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Ajustes de audio" })).toBeInTheDocument();

    rerender(<AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()} label="Ajustes" />);
    fireEvent.click(screen.getByRole("button", { name: "Ajustes" }));
    expect(screen.getByRole("dialog", { name: "Ajustes" })).toBeInTheDocument();
  });

  it("renders extra sections passed as children inside the dialog", () => {
    render(
      <AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()}>
        <p>Sección extra</p>
      </AudioSettingsOverlay>,
    );
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));
    expect(screen.getByRole("dialog")).toContainElement(screen.getByText("Sección extra"));
  });

  it("styles Cerrar like the other HUD actions, not as the generic secondary pill", () => {
    render(<AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));

    const close = screen.getByRole("button", { name: "Cerrar" });

    expect(close).toHaveClass("holo-frame", "holo");
    expect(close).not.toHaveClass("secondary");
  });

  it.each([/micrófono/i, /altavoz/i])("wraps the %s select in the HUD frame", (name) => {
    render(<AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));

    const select = screen.getByLabelText(name);

    expect(select.tagName).toBe("SELECT");
    expect(select.parentElement).toHaveClass("holo-frame", "select-frame");
  });

  it("gives render-prop children a close callback that dismisses the dialog", () => {
    render(
      <AudioSettingsOverlay devices={emptyDevices} onCommand={vi.fn()}>
        {(close) => (
          <button type="button" onClick={close}>
            Salir
          </button>
        )}
      </AudioSettingsOverlay>,
    );
    fireEvent.click(screen.getByRole("button", { name: /ajustes de audio/i }));

    fireEvent.click(screen.getByRole("button", { name: "Salir" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ajustes de audio/i })).toBeInTheDocument();
  });
});
