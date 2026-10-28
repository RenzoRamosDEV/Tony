import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends with Enter and clears the field", async () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);
    const field = screen.getByPlaceholderText("Escribe a Jarvis…");

    await userEvent.type(field, "hola{Enter}");

    expect(onSend).toHaveBeenCalledWith("hola");
    expect(field).toHaveValue("");
  });

  it("inserts a line break with Shift+Enter without sending", async () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);
    const field = screen.getByPlaceholderText("Escribe a Jarvis…");

    await userEvent.type(field, "uno{Shift>}{Enter}{/Shift}dos");

    expect(onSend).not.toHaveBeenCalled();
    expect(field).toHaveValue("uno\ndos");
  });

  it("ignores blank submissions", async () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);

    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "   {Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(onSend).not.toHaveBeenCalled();
  });

  it("sends the mode prefixes literally", async () => {
    const onSend = vi.fn();
    render(<Composer disabled={false} onSend={onSend} />);

    await userEvent.type(screen.getByPlaceholderText("Escribe a Jarvis…"), "/v qué hora es");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(onSend).toHaveBeenCalledWith("/v qué hora es");
  });

  it("is disabled with a visible indicator while Jarvis answers", () => {
    render(<Composer disabled={true} onSend={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(screen.getByPlaceholderText("Escribe a Jarvis…")).toBeDisabled();
    expect(screen.getByText("Jarvis está respondiendo…")).toBeInTheDocument();
  });
});

describe("Composer (review of change 04)", () => {
  it("finding 14: keeps the draft when the message could not be sent", async () => {
    const onSend = vi.fn().mockReturnValue(false);
    render(<Composer disabled={false} onSend={onSend} />);
    const field = screen.getByPlaceholderText("Escribe a Jarvis…");

    await userEvent.type(field, "hola{Enter}");

    expect(onSend).toHaveBeenCalledWith("hola");
    expect(field).toHaveValue("hola");
  });
});
