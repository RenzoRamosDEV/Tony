import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WindowBridge } from "../bridge/types";
import { TitleBar } from "./TitleBar";

function fakeControls(): WindowBridge {
  return {
    minimize: vi.fn(),
    toggleMaximize: vi.fn(),
    close: vi.fn(),
    startMove: vi.fn(),
    startResize: vi.fn(),
  };
}

describe("TitleBar", () => {
  it("renders nothing outside the desktop window", () => {
    const { container } = render(<TitleBar window={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the app title", () => {
    render(<TitleBar window={fakeControls()} />);
    expect(screen.getByText("Tony")).toBeInTheDocument();
  });

  it("starts a window move when the bar itself is pressed", () => {
    const controls = fakeControls();
    render(<TitleBar window={controls} />);

    fireEvent.mouseDown(screen.getByText("Tony").closest(".title-bar")!, { button: 0 });

    expect(controls.startMove).toHaveBeenCalledTimes(1);
  });

  it("does not start a move when a button inside the bar is pressed", () => {
    const controls = fakeControls();
    render(<TitleBar window={controls} />);

    fireEvent.mouseDown(screen.getByRole("button", { name: "Minimizar" }));

    expect(controls.startMove).not.toHaveBeenCalled();
  });

  it("toggles maximize on a double click on the bar itself", () => {
    const controls = fakeControls();
    render(<TitleBar window={controls} />);

    fireEvent.doubleClick(screen.getByText("Tony").closest(".title-bar")!);

    expect(controls.toggleMaximize).toHaveBeenCalledTimes(1);
  });

  it("calls minimize, toggleMaximize and close from their buttons", () => {
    const controls = fakeControls();
    render(<TitleBar window={controls} />);

    fireEvent.click(screen.getByRole("button", { name: "Minimizar" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximizar" }));
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));

    expect(controls.minimize).toHaveBeenCalledTimes(1);
    expect(controls.toggleMaximize).toHaveBeenCalledTimes(1);
    expect(controls.close).toHaveBeenCalledTimes(1);
  });
});
