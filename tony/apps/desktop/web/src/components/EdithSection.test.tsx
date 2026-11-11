import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AuthReason } from "../bridge/types";
import type { PinView } from "../state/reducer";
import { EdithSection } from "./EdithSection";

function view(reason: AuthReason | null, locked: boolean): PinView {
  return { mode: "hidden", message: "", retryAt: 0, canUnlock: locked, reason };
}

function renderSection(pin: PinView) {
  const onCommand = vi.fn();
  const onUnlockRequest = vi.fn();
  render(<EdithSection pin={pin} onCommand={onCommand} onUnlockRequest={onUnlockRequest} />);
  return { onCommand, onUnlockRequest };
}

describe("EdithSection", () => {
  it("is a labelled Edith group", () => {
    renderSection(view("unlocked", false));

    expect(screen.getByRole("group", { name: "Edith" })).toBeInTheDocument();
  });

  it("shows an unlocked session with a Bloquear button that sends lock", () => {
    const { onCommand, onUnlockRequest } = renderSection(view("unlocked", false));

    expect(screen.getByText("Desbloqueada")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bloquear" }));

    expect(onCommand).toHaveBeenCalledExactlyOnceWith({ type: "lock" });
    expect(onUnlockRequest).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Introducir PIN" })).toBeNull();
  });

  it.each<AuthReason>(["start", "locked_by_user", "idle", "cancelled", "wrong_pin", "backoff"])(
    "shows a locked session (%s) with Introducir PIN reusing the unlock request",
    (reason) => {
      const { onCommand, onUnlockRequest } = renderSection(view(reason, true));

      expect(screen.getByText("Bloqueada")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Introducir PIN" }));

      expect(onUnlockRequest).toHaveBeenCalledOnce();
      expect(onCommand).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: "Bloquear" })).toBeNull();
    },
  );

  it.each<[AuthReason, boolean]>([
    ["no_lock_file", true],
    ["not_required", false],
  ])("explains there is no PIN (%s) without any button", (reason, locked) => {
    renderSection(view(reason, locked));

    expect(screen.getByText(/tony pin set/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows no state and no button before the first auth event", () => {
    renderSection(view(null, false));

    expect(screen.queryByText(/Bloqueada|Desbloqueada|tony pin set/)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
