import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmationCard } from "./ConfirmationCard";

const ARGS = { source: "/n/a.md", destination: "/n/.trash/a.md" };

function card(expiresInS: number, onAnswer = vi.fn()) {
  const confirmation = {
    confirmationId: "a3f",
    taskId: "t-9",
    tool: "filesystem.move_file",
    args: ARGS,
    deadline: Date.now() + expiresInS * 1000,
  };
  return { ...render(<ConfirmationCard confirmation={confirmation} onAnswer={onAnswer} />), onAnswer };
}

describe("ConfirmationCard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the tool, the formatted args and the countdown from 60", () => {
    card(60);

    expect(screen.getByText("filesystem.move_file")).toBeInTheDocument();
    expect(document.querySelector("pre")?.textContent).toBe(JSON.stringify(ARGS, null, 2));
    expect(screen.getByText(/60 s/)).toBeInTheDocument();
  });

  it("counts down from the remaining seconds on reconnection", () => {
    card(39);
    expect(screen.getByText(/39 s/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getByText(/37 s/)).toBeInTheDocument();
  });

  it("answers with the buttons", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { onAnswer } = card(60);

    await user.click(screen.getByRole("button", { name: "Confirmar" }));
    await user.click(screen.getByRole("button", { name: "Rechazar" }));

    expect(onAnswer.mock.calls).toEqual([["a3f", true], ["a3f", false]]);
  });

  it("replaces the buttons by the expired notice at zero", () => {
    card(2);

    act(() => {
      vi.advanceTimersByTime(2100);
    });

    expect(screen.queryByRole("button", { name: "Confirmar" })).toBeNull();
    expect(screen.getByText("Confirmación caducada")).toBeInTheDocument();
  });
});
