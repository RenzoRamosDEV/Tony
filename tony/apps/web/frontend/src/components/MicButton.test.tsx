import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MicButton } from "./MicButton";

describe("MicButton", () => {
  it("calls onToggle when clicked", async () => {
    const onToggle = vi.fn();
    render(<MicButton mic="off" phase="idle" available={true} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("button", { name: /micrófono/i }));

    expect(onToggle).toHaveBeenCalled();
  });

  it("is disabled when voice is unavailable", () => {
    render(<MicButton mic="off" phase="idle" available={false} onToggle={vi.fn()} />);

    expect(screen.getByRole("button", { name: /micrófono/i })).toBeDisabled();
  });

  it("reflects the on state and phase", () => {
    render(<MicButton mic="on" phase="listening" available={true} onToggle={vi.fn()} />);

    const button = screen.getByRole("button", { name: /micrófono/i });
    expect(button).toHaveAttribute("data-mic-state", "on");
    expect(button).toHaveAttribute("data-voice-phase", "listening");
  });
});
