import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble, WaitBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("shows the user text literally with its effective mode", () => {
    render(<MessageBubble message={{ id: "u1", role: "user", content: "**no negrita** <b>x</b>", effectiveMode: "voice" }} />);

    expect(screen.getByText("**no negrita** <b>x</b>")).toBeInTheDocument();
    expect(document.querySelector("strong, b")).toBeNull();
    expect(screen.getByText("voice")).toBeInTheDocument();
    expect(screen.getByRole("article")).toHaveAttribute("data-role", "user");
  });

  it("renders the assistant text as sanitised markdown", () => {
    render(<MessageBubble message={{ id: "a1", role: "assistant", content: "Hola <img src=x onerror=alert(1)> **ok**" }} />);

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("ok").tagName).toBe("STRONG");
    expect(screen.getByRole("article")).toHaveAttribute("data-role", "assistant");
  });

  it("marks a streaming message", () => {
    render(<MessageBubble message={{ id: "a1", role: "assistant", content: "Hol", streaming: true }} />);

    expect(screen.getByRole("article")).toHaveAttribute("data-streaming", "true");
  });

  it("renders the wait phrase as a muted bubble", () => {
    render(<WaitBubble text="Dame un momento." />);

    const bubble = screen.getByText("Dame un momento.");
    expect(bubble.closest("[data-role='wait']")).not.toBeNull();
  });
});
