import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VoiceStateName } from "../bridge/types";
import { MicButton } from "./MicButton";

function mic(state: VoiceStateName, reason: string | null = null) {
  const onCommand = vi.fn();
  render(<MicButton voice={{ state, reason }} onCommand={onCommand} />);
  return onCommand;
}

describe("MicButton", () => {
  it("sends listen when ready", async () => {
    const onCommand = mic("ready");

    await userEvent.click(screen.getByRole("button", { name: "Micrófono" }));

    expect(onCommand.mock.calls).toEqual([[{ type: "listen" }]]);
  });

  it("sends stop_listening while listening", async () => {
    const onCommand = mic("listening");

    await userEvent.click(screen.getByRole("button", { name: "Escuchando…" }));

    expect(onCommand.mock.calls).toEqual([[{ type: "stop_listening" }]]);
  });

  it.each([
    ["loading", null, "Cargando los modelos de voz…"],
    ["unavailable", "sin extra voice", "Voz no disponible: sin extra voice"],
  ] as const)("is disabled with a tooltip while %s", (state, reason, tooltip) => {
    mic(state, reason);
    const button = screen.getByRole("button", { name: "Micrófono" });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", tooltip);
  });

  it("exposes the voice state for styling", () => {
    mic("listening");

    expect(screen.getByRole("button")).toHaveAttribute("data-voice-state", "listening");
  });
});
