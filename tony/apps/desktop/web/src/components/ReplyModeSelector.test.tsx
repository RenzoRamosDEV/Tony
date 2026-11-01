import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReplyModeSelector } from "./ReplyModeSelector";

describe("ReplyModeSelector", () => {
  it("offers the four reply modes", () => {
    render(<ReplyModeSelector mode="auto" onCommand={vi.fn()} />);

    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.value)).toEqual(["auto", "voice", "text", "both"]);
  });

  it("reflects the current reply mode", () => {
    render(<ReplyModeSelector mode="both" onCommand={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: "Modo de respuesta" })).toHaveValue("both");
  });

  it("sends set_mode when another mode is selected", async () => {
    const onCommand = vi.fn();
    render(<ReplyModeSelector mode="auto" onCommand={onCommand} />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "voice");

    expect(onCommand.mock.calls).toEqual([[{ type: "set_mode", mode: "voice" }]]);
  });
});
