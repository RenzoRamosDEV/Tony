import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModeSelector } from "./ModeSelector";

function fetchReturning(status: number, body: unknown) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status });
  };
  return { calls, fetchImpl };
}

describe("ModeSelector", () => {
  it("patches the settings and marks the pressed mode active", async () => {
    const { calls, fetchImpl } = fetchReturning(200, { reply_mode: "voice", reply_mode_source: "settings" });
    const onChanged = vi.fn();
    render(<ModeSelector value="auto" fetchImpl={fetchImpl} onChanged={onChanged} />);

    await userEvent.click(screen.getByRole("radio", { name: "voice" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith("voice"));
    expect(calls[0]?.url).toBe("/api/settings");
    expect(calls[0]?.init?.method).toBe("PATCH");
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ reply_mode: "voice" });
    expect(screen.getByRole("radio", { name: "voice" })).toBeChecked();
  });

  it("shows a warning and restores the previous mode when the PATCH fails", async () => {
    const { fetchImpl } = fetchReturning(422, { error: "validation_error", detail: "modo inválido" });
    const onChanged = vi.fn();
    render(<ModeSelector value="text" fetchImpl={fetchImpl} onChanged={onChanged} />);

    await userEvent.click(screen.getByRole("radio", { name: "both" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("modo inválido"));
    expect(screen.getByRole("radio", { name: "text" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "both" })).not.toBeChecked();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("reflects the reply_mode received by props", () => {
    const { fetchImpl } = fetchReturning(200, {});
    const { rerender } = render(<ModeSelector value="auto" fetchImpl={fetchImpl} onChanged={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "auto" })).toBeChecked();

    rerender(<ModeSelector value="text" fetchImpl={fetchImpl} onChanged={vi.fn()} />);

    expect(screen.getByRole("radio", { name: "text" })).toBeChecked();
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual(["auto", "voice", "text", "both"]);
  });
});
