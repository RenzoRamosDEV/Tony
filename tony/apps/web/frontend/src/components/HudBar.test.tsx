import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VoiceState } from "../protocol/types";
import { HudBar, type HudBarProps } from "./HudBar";

const VOICE: VoiceState = { available: true, reason: null, mic: "on", phase: "listening", speakingMessageId: null };

function bar(overrides: Partial<HudBarProps> = {}) {
  const props: HudBarProps = {
    voice: VOICE,
    level: 0.1,
    speaking: true,
    replyMode: "text",
    onModeChanged: vi.fn(),
    fetchImpl: vi.fn(async () => new Response("{}")),
    inputDisabled: false,
    onSend: vi.fn(() => true),
    onToggleMic: vi.fn(),
    onStopAudio: vi.fn(),
    canCancel: true,
    onCancel: vi.fn(),
    ...overrides,
  };
  render(<HudBar {...props} />);
  return { props, toolbar: screen.getByRole("group", { name: "Controles de Jarvis" }) };
}

describe("HudBar", () => {
  it("holds the input, microphone, voice status, mode selector, stop audio and cancel", () => {
    const { toolbar } = bar();
    const inside = within(toolbar);

    expect(inside.getByRole("textbox", { name: "Mensaje para Jarvis" })).toBeInTheDocument();
    expect(inside.getByRole("button", { name: "Desactivar micrófono" })).toBeInTheDocument();
    expect(inside.getByRole("meter", { name: "Nivel de entrada" })).toBeInTheDocument();
    expect(inside.getByRole("status")).toHaveTextContent("Hablando…");
    expect(inside.getByRole("radiogroup", { name: "Modo de respuesta" })).toBeInTheDocument();
    expect(inside.getByRole("button", { name: "Detener audio" })).toBeInTheDocument();
    expect(inside.getByRole("button", { name: /Cancelar tarea/ })).toBeInTheDocument();
  });

  it("keeps every handler", async () => {
    const user = userEvent.setup();
    const { props, toolbar } = bar();
    const inside = within(toolbar);

    await user.type(inside.getByRole("textbox"), "hola{Enter}");
    await user.click(inside.getByRole("button", { name: "Desactivar micrófono" }));
    await user.click(inside.getByRole("button", { name: "Detener audio" }));
    await user.click(inside.getByRole("button", { name: /Cancelar tarea/ }));

    expect(props.onSend).toHaveBeenCalledWith("hola");
    expect(props.onToggleMic).toHaveBeenCalledTimes(1);
    expect(props.onStopAudio).toHaveBeenCalledTimes(1);
    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("hides cancel without a running task and stop audio while silent", () => {
    bar({ canCancel: false, speaking: false });

    expect(screen.queryByRole("button", { name: /Cancelar tarea/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Detener audio" })).toBeNull();
  });

  it("shows the speaking phase while audio plays", () => {
    bar({ voice: { ...VOICE, mic: "off", phase: "idle" }, speaking: true });

    expect(screen.getByText("Hablando…")).toBeInTheDocument();
  });
});
