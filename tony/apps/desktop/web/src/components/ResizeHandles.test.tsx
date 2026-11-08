import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { WindowBridge } from "../bridge/types";
import { ResizeHandles } from "./ResizeHandles";

function fakeControls(): WindowBridge {
  return {
    minimize: vi.fn(),
    toggleMaximize: vi.fn(),
    close: vi.fn(),
    startMove: vi.fn(),
    startResize: vi.fn(),
  };
}

describe("ResizeHandles", () => {
  it("renders nothing outside the desktop window", () => {
    const { container } = render(<ResizeHandles window={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one handle per edge, each wired to its own resize edge", () => {
    const controls = fakeControls();
    const { container } = render(<ResizeHandles window={controls} />);

    const handles = container.querySelectorAll(".resize-handle");
    expect(handles).toHaveLength(8);

    const bottomRight = container.querySelector(".resize-bottom-right")!;
    bottomRight.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));

    expect(controls.startResize).toHaveBeenCalledWith("bottom-right");
    expect(controls.startResize).toHaveBeenCalledTimes(1);
  });
});
