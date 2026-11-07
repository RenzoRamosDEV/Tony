import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CollapsiblePanel } from "./CollapsiblePanel";

describe("CollapsiblePanel frame", () => {
  it("wears the shared holo button frame instead of the rounded glass card", () => {
    render(
      <CollapsiblePanel title="Actividad" className="activity-panel">
        <p>contenido</p>
      </CollapsiblePanel>,
    );

    const card = screen.getByRole("region", { name: "Actividad" });

    expect(card).toHaveClass("side-panel", "holo-frame", "activity-panel");
    expect(card).not.toHaveClass("hud-panel");
    expect(card).not.toHaveClass("holo");
  });
});
