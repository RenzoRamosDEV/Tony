import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VoiceState } from "../protocol/types";
import { MicButton } from "./MicButton";

const base: VoiceState = { available: true, reason: null, mic: "off", phase: "idle", speakingMessageId: null };

describe("MicButton", () => {
  it("is a toggle with Spanish labels and aria-pressed", async () => {
    const onToggle = vi.fn();
    const { rerender } = render(<MicButton voice={base} onToggle={onToggle} />);
    const off = screen.getByRole("button", { name: "Activar micrófono" });
    expect(off).toHaveAttribute("aria-pressed", "false");
    expect(off).toBeEnabled();

    await userEvent.click(off);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(<MicButton voice={{ ...base, mic: "on", phase: "listening" }} onToggle={onToggle} />);
    const on = screen.getByRole("button", { name: "Desactivar micrófono" });
    expect(on).toHaveAttribute("aria-pressed", "true");
    expect(on.className).toContain("active");
  });

  it("is disabled with the reason and the install command when voice is unavailable", () => {
    render(<MicButton voice={{ ...base, available: false, reason: "extra tony[voice] no instalado" }} onToggle={() => undefined} />);

    const button = screen.getByRole("button", { name: "Activar micrófono" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", expect.stringContaining("extra tony[voice] no instalado"));
    expect(button).toHaveAttribute("title", expect.stringContaining("uv sync --extra voice"));
  });

  it("stays enabled while the availability is still unknown", () => {
    render(<MicButton voice={{ ...base, available: null }} onToggle={() => undefined} />);

    expect(screen.getByRole("button")).toBeEnabled();
  });
});
