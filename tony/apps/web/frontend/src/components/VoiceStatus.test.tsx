import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { VoiceState } from "../protocol/types";
import { VoiceStatus } from "./VoiceStatus";

const on: VoiceState = { available: true, reason: null, mic: "on", phase: "listening", speakingMessageId: null, pendingMeta: null };

describe("VoiceStatus", () => {
  it.each([
    ["listening", "Escuchando…"],
    ["transcribing", "Transcribiendo…"],
    ["speaking", "Hablando…"],
  ] as const)("shows the phase text for %s", (phase, text) => {
    render(<VoiceStatus voice={{ ...on, phase }} level={0} />);

    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it("renders nothing when idle with the microphone off", () => {
    render(<VoiceStatus voice={{ ...on, mic: "off", phase: "idle" }} level={0} />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("meter")).toBeNull();
  });

  it("exposes the input level as a meter while the microphone is on", () => {
    const { rerender } = render(<VoiceStatus voice={on} level={0.1} />);
    const meter = screen.getByRole("meter", { name: "Nivel de entrada" });
    expect(meter).toHaveAttribute("aria-valuenow", "50");
    expect(meter).toHaveAttribute("aria-valuemax", "100");

    rerender(<VoiceStatus voice={on} level={0.9} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "100");
  });
});
