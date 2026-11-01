import { act, fireEvent, render, screen } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthEvent, AuthReason, Command } from "../bridge/types";
import { initialState, reduce, type UiState } from "../state/reducer";
import { PinOverlay } from "./PinOverlay";

let latest: UiState;
let sent: Command[];

function Harness({ events }: { events: AuthEvent[] }) {
  const [state, dispatch] = useReducer(reduce, undefined, () =>
    events.reduce((s, event) => reduce(s, { kind: "event", event, now: Date.now() }), initialState()),
  );
  latest = state;
  return (
    <PinOverlay
      pin={state.pin}
      onCommand={(command) => sent.push(command)}
      onHide={() => dispatch({ kind: "pin_cancelled" })}
      onUnlockRequest={() => dispatch({ kind: "unlock_requested" })}
    />
  );
}

function auth(reason: AuthReason, retry = 0, state: "locked" | "unlocked" = "locked"): AuthEvent {
  return { type: "auth", ts: "t", state, reason, retry_in_s: retry };
}

function show(...events: AuthEvent[]) {
  render(<Harness events={events} />);
}

const field = () => screen.queryByLabelText("PIN") as HTMLInputElement | null;

beforeEach(() => {
  sent = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
  sessionStorage.clear();
});

describe("PinOverlay", () => {
  it.each(["start", "idle", "wrong_pin", "backoff"] as const)("asks for the PIN on %s", (reason) => {
    show(auth(reason));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(field()).toHaveAttribute("type", "password");
    expect(field()).toBeEnabled();
  });

  it("shows nothing while unlocked", () => {
    show(auth("unlocked", 0, "unlocked"));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts the back-off down and enables the field at 0 s", () => {
    show(auth("wrong_pin", 10));
    expect(field()).toBeDisabled();
    expect(screen.getByText(/10 s/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(9000);
    });
    expect(field()).toBeDisabled();
    expect(screen.getByText(/1 s/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(field()).toBeEnabled();
    expect(screen.queryByText(/\d+ s/)).toBeNull();
  });

  it("explains a missing lock file without a PIN field", () => {
    show(auth("no_lock_file"));

    expect(screen.getByRole("dialog")).toHaveTextContent("tony pin set");
    expect(field()).toBeNull();
    expect(screen.queryByRole("button", { name: "Desbloquear" })).toBeNull();
  });

  it("cancel sends an unlock without PIN and hides the overlay", () => {
    show(auth("start"));

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(sent).toEqual([{ type: "unlock", pin: null }]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("submits the PIN once, clears the field and keeps it nowhere", () => {
    show(auth("start"));
    const input = field() as HTMLInputElement;

    fireEvent.change(input, { target: { value: "1234" } });
    fireEvent.click(screen.getByRole("button", { name: "Desbloquear" }));

    expect(sent).toEqual([{ type: "unlock", pin: "1234" }]);
    expect(input.value).toBe("");
    expect(JSON.stringify(latest)).not.toContain("1234");
    expect(JSON.stringify({ ...localStorage })).not.toContain("1234");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("1234");
  });

  it("does not submit an empty PIN", () => {
    show(auth("start"));

    fireEvent.click(screen.getByRole("button", { name: "Desbloquear" }));

    expect(sent).toEqual([]);
  });

  it("offers an unlock control while locked that reopens the overlay", () => {
    show(auth("cancelled"));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Introducir PIN" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(field()).toBeEnabled();
  });
});
