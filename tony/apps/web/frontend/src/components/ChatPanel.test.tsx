import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";
import type { Message } from "../protocol/reducer";

const MESSAGES: Message[] = [
  { id: "1", role: "user", content: "hola", seq: 1 },
  { id: "2", role: "assistant", content: "qué tal", seq: 2 },
];

describe("ChatPanel", () => {
  it("shows an empty-state placeholder with no messages", () => {
    render(<ChatPanel messages={[]} turnInProgress={false} onSend={vi.fn()} />);

    expect(screen.getByText(/la conversación aparece aquí/i)).toBeInTheDocument();
  });

  it("shows the messages oldest to newest, labelled by speaker", () => {
    render(<ChatPanel messages={MESSAGES} turnInProgress={false} onSend={vi.fn()} />);

    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["RENZO: hola", "JARVIS: qué tal"]);
  });

  it("keeps the whole history, letting a long conversation scroll", () => {
    const long: Message[] = Array.from({ length: 30 }, (_, i) => ({
      id: String(i),
      role: i % 2 === 0 ? "user" : "assistant",
      content: `mensaje ${i}`,
      seq: i,
    }));

    render(<ChatPanel messages={long} turnInProgress={false} onSend={vi.fn()} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(30);
    expect(items[0]).toHaveTextContent("mensaje 0");
    expect(items.at(-1)).toHaveTextContent("mensaje 29");
  });

  it("sends the typed text and clears the input", async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} turnInProgress={false} onSend={onSend} />);

    const input = screen.getByRole("textbox");
    await userEvent.type(input, "hola mundo");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(onSend).toHaveBeenCalledWith("hola mundo");
    expect(input).toHaveValue("");
  });

  it("disables sending while a turn is in progress or the input is empty", () => {
    render(<ChatPanel messages={[]} turnInProgress={true} onSend={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  });
});
