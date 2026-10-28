import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageBubble, WaitBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  it("shows the user text literally with its effective mode", () => {
    render(<MessageBubble message={{ id: "u1", role: "user", content: "**no negrita** <b>x</b>", seq: 1, effectiveMode: "voice" }} />);

    expect(screen.getByText("**no negrita** <b>x</b>")).toBeInTheDocument();
    expect(document.querySelector("strong, b")).toBeNull();
    expect(screen.getByText("voice")).toBeInTheDocument();
    expect(screen.getByRole("article")).toHaveAttribute("data-role", "user");
  });

  it("renders the assistant text as sanitised markdown", () => {
    render(<MessageBubble message={{ id: "a1", role: "assistant", content: "Hola <img src=x onerror=alert(1)> **ok**", seq: 2 }} />);

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("ok").tagName).toBe("STRONG");
    expect(screen.getByRole("article")).toHaveAttribute("data-role", "assistant");
  });

  it("marks a streaming message", () => {
    render(<MessageBubble message={{ id: "a1", role: "assistant", content: "Hol", seq: 3, streaming: true }} />);

    expect(screen.getByRole("article")).toHaveAttribute("data-streaming", "true");
  });

  it("renders the wait phrase as a muted bubble", () => {
    render(<WaitBubble text="Dame un momento." />);

    const bubble = screen.getByText("Dame un momento.");
    expect(bubble.closest("[data-role='wait']")).not.toBeNull();
  });
});

describe("MessageBubble (voice)", () => {
  it("marks a transcribed user message with a microphone icon and its mode", () => {
    render(
      <MessageBubble
        message={{ id: "m-1", role: "user", content: "¿qué hora es?", seq: 4, source: "voice", effectiveMode: "voice" }}
      />,
    );

    const article = screen.getByRole("article");
    expect(article).toHaveAttribute("data-source", "voice");
    expect(article).toHaveAccessibleName("Mensaje tuyo por voz");
    expect(screen.getByTitle("Transcrito del micrófono")).toBeInTheDocument();
    expect(screen.getByText("voice")).toBeInTheDocument();
    expect(screen.getByText("¿qué hora es?")).toBeInTheDocument();
  });

  it("typed messages carry no microphone icon", () => {
    render(<MessageBubble message={{ id: "u1", role: "user", content: "hola", seq: 1, effectiveMode: "text" }} />);

    expect(screen.queryByTitle("Transcrito del micrófono")).toBeNull();
    expect(screen.getByRole("article")).not.toHaveAttribute("data-source");
  });
});
