import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Message } from "../protocol/reducer";
import { Subtitles } from "./Subtitles";

function message(id: string, role: Message["role"], content: string, extra: Partial<Message> = {}): Message {
  return { id, role, content, seq: 1, ...extra };
}

function region(): HTMLElement {
  return screen.getByRole("region", { name: "Subtítulos" });
}

describe("Subtitles", () => {
  it("shows the empty prompt without messages", () => {
    render(<Subtitles messages={[]} waitText={null} />);

    expect(region()).toHaveTextContent("Escribe a Jarvis…");
  });

  it("announces politely", () => {
    render(<Subtitles messages={[]} waitText={null} />);

    expect(region()).toHaveAttribute("aria-live", "polite");
  });

  it("shows only the last user message and the reply that follows it", () => {
    render(
      <Subtitles
        messages={[
          message("1", "user", "primera"),
          message("2", "assistant", "respuesta vieja"),
          message("3", "user", "hola"),
          message("4", "assistant", "Hola, Renzo."),
        ]}
        waitText={null}
      />,
    );

    expect(region()).toHaveTextContent("hola");
    expect(region()).toHaveTextContent("Hola, Renzo.");
    expect(region()).not.toHaveTextContent("primera");
    expect(region()).not.toHaveTextContent("respuesta vieja");
    expect(screen.queryByText("Escribe a Jarvis…")).toBeNull();
  });

  it("does not pair a new question with the previous answer", () => {
    render(
      <Subtitles
        messages={[message("1", "user", "primera"), message("2", "assistant", "vieja"), message("3", "user", "nueva")]}
        waitText={null}
      />,
    );

    expect(region()).toHaveTextContent("nueva");
    expect(region()).not.toHaveTextContent("vieja");
  });

  it("shows the streaming reply once, without duplicating text", () => {
    render(
      <Subtitles
        messages={[message("1", "user", "hola"), message("2", "assistant", "Hola", { streaming: true })]}
        waitText={null}
      />,
    );

    expect(screen.getAllByText("Hola")).toHaveLength(1);
    expect(document.querySelector('[data-streaming="true"]')).not.toBeNull();
  });

  it("shows the wait bubble while the reply has not started", () => {
    render(<Subtitles messages={[message("1", "user", "hola")]} waitText="Pensando…" />);

    expect(region()).toHaveTextContent("Pensando…");
    expect(document.querySelector('[data-role="wait"]')).not.toBeNull();
  });

  it("renders the reply as sanitised markdown", () => {
    render(
      <Subtitles
        messages={[
          message("1", "user", "hola"),
          message("2", "assistant", "**negrita** <img src=x onerror=alert(1)>"),
        ]}
        waitText={null}
      />,
    );

    expect(region().querySelector("strong")).toHaveTextContent("negrita");
    expect(region().querySelector("img[onerror]")).toBeNull();
  });

  it("shows a lone assistant message when there is no user message", () => {
    render(<Subtitles messages={[message("1", "assistant", "Bienvenido")]} waitText={null} />);

    expect(region()).toHaveTextContent("Bienvenido");
  });
});
