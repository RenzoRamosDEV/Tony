import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../state/reducer";
import { ChatPanel } from "./ChatPanel";

function message(id: number, over: Partial<ChatMessage> = {}): ChatMessage {
  return { id, kind: "agent", agent: "jarvis", label: "Jarvis", colour: "#2F6FED", text: `mensaje ${id}`, open: false, ...over };
}

const MESSAGES: ChatMessage[] = [
  message(1, { kind: "user", agent: "user", label: "Tú", colour: "#6B7280", text: "hola" }),
  message(2, { text: "qué tal" }),
];

describe("ChatPanel", () => {
  it("shows an empty-state placeholder with no messages", () => {
    render(<ChatPanel messages={[]} onSend={vi.fn()} />);

    expect(screen.getByText(/la conversación aparece aquí/i)).toBeInTheDocument();
  });

  it("shows the messages oldest to newest, labelled by speaker", () => {
    render(<ChatPanel messages={MESSAGES} onSend={vi.fn()} />);

    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.textContent?.trim())).toEqual(["Tú: hola", "Jarvis: qué tal"]);
  });

  it("colours the speaker label with the agent colour", () => {
    render(<ChatPanel messages={MESSAGES} onSend={vi.fn()} />);

    expect(screen.getByText("Jarvis:")).toHaveStyle({ color: "#2F6FED" });
  });

  it("renders agent Markdown as HTML", () => {
    render(<ChatPanel messages={[message(1, { text: "**hecho** y `x`" })]} onSend={vi.fn()} />);

    expect(screen.getByText("hecho").tagName).toBe("STRONG");
    expect(screen.getByText("x").tagName).toBe("CODE");
  });

  it("shows user text as typed, without Markdown", () => {
    render(<ChatPanel messages={[message(1, { kind: "user", label: "Tú", text: "**literal**" })]} onSend={vi.fn()} />);

    expect(screen.getByText("**literal**")).toBeInTheDocument();
  });

  it("keeps the whole history and scrolls to the newest message", () => {
    const long = Array.from({ length: 30 }, (_, i) => message(i));
    const { rerender } = render(<ChatPanel messages={long.slice(0, 29)} onSend={vi.fn()} />);
    const list = screen.getByRole("list");
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 1234 });

    rerender(<ChatPanel messages={long} onSend={vi.fn()} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(30);
    expect(list.scrollTop).toBe(1234);
  });

  it("sends the trimmed text on Enter and clears the input", async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} />);

    const input = screen.getByRole("textbox", { name: "Mensaje" });
    await userEvent.type(input, "  hola mundo  {Enter}");

    expect(onSend.mock.calls).toEqual([["hola mundo"]]);
    expect(input).toHaveValue("");
  });

  it("sends with the button too", async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "hola");
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));

    expect(onSend.mock.calls).toEqual([["hola"]]);
  });

  it("ignores empty and whitespace-only text", async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Mensaje" }), "   {Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  });
});
