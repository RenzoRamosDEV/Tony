import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EngineSelector } from "./EngineSelector";

const VIEW = {
  active: "claude_sdk",
  profiles: [
    { name: "claude_sdk", type: "claude_sdk", model: "claude" },
    { name: "codex", type: "codex", model: "gpt" },
  ],
};

function api(overrides: Partial<ReturnType<typeof baseApi>> = {}) {
  return { ...baseApi(), ...overrides };
}

function baseApi() {
  return {
    getEngines: vi.fn().mockResolvedValue(VIEW),
    patchEngine: vi.fn().mockResolvedValue({ ...VIEW, active: "codex" }),
  };
}

describe("EngineSelector", () => {
  it("loads the engine profiles and selects the active one", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={false} />);

    await waitFor(() => expect(theApi.getEngines).toHaveBeenCalled());
    expect(await screen.findByRole("combobox")).toHaveValue("claude_sdk");
  });

  it("switches the active engine on change", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "codex");

    expect(theApi.patchEngine).toHaveBeenCalledWith("codex");
    await waitFor(() => expect(select).toHaveValue("codex"));
  });

  it("shows an error notice when switching fails", async () => {
    const theApi = api({ patchEngine: vi.fn().mockRejectedValue(new Error("no se pudo cambiar")) });
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "codex");

    expect(await screen.findByText("no se pudo cambiar")).toBeInTheDocument();
  });

  it("disables the selector while busy", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={true} />);

    expect(await screen.findByRole("combobox")).toBeDisabled();
  });
});
