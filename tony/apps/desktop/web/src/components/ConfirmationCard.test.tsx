import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { NeedsConfirmationEvent } from "../bridge/types";
import { ConfirmationCard } from "./ConfirmationCard";

function confirmation(tool: string, allowAlways: boolean): NeedsConfirmationEvent {
  return {
    type: "needs_confirmation",
    ts: "t",
    task_id: "t1",
    tool,
    args_preview: '{"path": "a.md"}',
    question: "¿Autoriza borrar a.md?",
    allow_always: allowAlways,
  };
}

function card(tool = "filesystem.delete_file", allowAlways = true, focusRequest = 0) {
  const onAnswer = vi.fn();
  const view = render(
    <ConfirmationCard confirmation={confirmation(tool, allowAlways)} onAnswer={onAnswer} focusRequest={focusRequest} />,
  );
  return { ...view, onAnswer };
}

describe("ConfirmationCard", () => {
  it("shows the question, the tool and the masked arguments as text", () => {
    card();

    expect(screen.getByText("¿Autoriza borrar a.md?")).toBeInTheDocument();
    expect(screen.getByText("filesystem.delete_file")).toBeInTheDocument();
    expect(document.querySelector("pre")?.textContent).toBe('{"path": "a.md"}');
  });

  it.each([
    ["Permitir", "allow"],
    ["Denegar", "deny"],
    ["Permitir siempre", "always"],
  ])("«%s» answers %s for the task", async (name, decision) => {
    const { onAnswer } = card();

    await userEvent.click(screen.getByRole("button", { name }));

    expect(onAnswer.mock.calls).toEqual([[{ type: "confirm", task_id: "t1", decision }]]);
  });

  it("hides «Permitir siempre» for a tool with a deny rule", () => {
    card("shell.run", false);

    expect(screen.getByRole("button", { name: "Permitir" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Denegar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Permitir siempre" })).toBeNull();
  });

  it("shows «Permitir siempre» enabled for a tool without a deny rule", () => {
    card("filesystem.delete_file", true);

    expect(screen.getByRole("button", { name: "Permitir siempre" })).toBeEnabled();
  });

  it("focuses «Denegar» when it appears", () => {
    card();

    expect(screen.getByRole("button", { name: "Denegar" })).toHaveFocus();
  });

  it("focuses «Denegar» again on a focus request", () => {
    const { rerender, onAnswer } = card();
    screen.getByRole("button", { name: "Permitir" }).focus();

    rerender(
      <ConfirmationCard confirmation={confirmation("filesystem.delete_file", true)} onAnswer={onAnswer} focusRequest={1} />,
    );

    expect(screen.getByRole("button", { name: "Denegar" })).toHaveFocus();
  });
});
