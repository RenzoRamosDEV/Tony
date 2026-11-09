import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppearanceSection } from "./AppearanceSection";

describe("AppearanceSection", () => {
  it("exposes the three themes as a labelled radiogroup", () => {
    render(<AppearanceSection theme="holo" onChange={vi.fn()} />);

    const group = screen.getByRole("radiogroup", { name: /apariencia/i });
    const radios = screen.getAllByRole("radio");
    expect(group).toBeInTheDocument();
    expect(radios.map((radio) => radio.getAttribute("aria-label") ?? radio.closest("label")?.textContent)).toEqual([
      expect.stringContaining("Holo Ámbar"),
      expect.stringContaining("Aurora"),
      expect.stringContaining("Instrumento"),
    ]);
  });

  it.each([
    ["holo", "Holo Ámbar"],
    ["aurora", "Aurora"],
    ["instrumento", "Instrumento"],
  ] as const)("checks only the active theme (%s)", (theme, name) => {
    render(<AppearanceSection theme={theme} onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: new RegExp(name) })).toBeChecked();
    expect(screen.getAllByRole("radio").filter((radio) => (radio as HTMLInputElement).checked)).toHaveLength(1);
  });

  it("reports the chosen theme", () => {
    const onChange = vi.fn();
    render(<AppearanceSection theme="holo" onChange={onChange} />);

    fireEvent.click(screen.getByRole("radio", { name: /aurora/i }));

    expect(onChange).toHaveBeenCalledWith("aurora");
  });

  it("is operable with the arrow keys", async () => {
    const onChange = vi.fn();
    render(<AppearanceSection theme="holo" onChange={onChange} />);

    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith("aurora");
  });

  it("gives every option a colour swatch tagged with its theme", () => {
    const { container } = render(<AppearanceSection theme="holo" onChange={vi.fn()} />);

    const swatches = Array.from(container.querySelectorAll(".theme-swatch")).map((el) => el.getAttribute("data-theme"));
    expect(swatches).toEqual(["holo", "aurora", "instrumento"]);
  });
});
