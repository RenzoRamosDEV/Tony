import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StatusBanner } from "./StatusBanner";

describe("StatusBanner", () => {
  it("announces the disconnection while reconnecting", () => {
    render(<StatusBanner connected={false} notice={null} onDismiss={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("Desconectado, reintentando…");
  });

  it("renders nothing when connected without notice", () => {
    const { container } = render(<StatusBanner connected={true} notice={null} onDismiss={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the notice with a dismiss button", async () => {
    const onDismiss = vi.fn();
    render(<StatusBanner connected={true} notice="espera a que termine" onDismiss={onDismiss} />);

    expect(screen.getByRole("alert")).toHaveTextContent("espera a que termine");
    await userEvent.click(screen.getByRole("button", { name: "Cerrar aviso" }));

    expect(onDismiss).toHaveBeenCalled();
  });
});
