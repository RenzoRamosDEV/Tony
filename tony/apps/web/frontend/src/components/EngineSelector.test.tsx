import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EngineSelector } from "./EngineSelector";

const VIEW = {
  active: "claude_sdk",
  profiles: [
    { name: "claude_sdk", type: "claude_sdk", model: "claude" },
    { name: "other", type: "other", model: "gpt" },
    { name: "openai-api", type: "litellm", model: "gpt-4", auth: "api_key", configured: false },
  ],
};

function api(overrides: Partial<ReturnType<typeof baseApi>> = {}) {
  return { ...baseApi(), ...overrides };
}

function baseApi() {
  return {
    getEngines: vi.fn().mockResolvedValue(VIEW),
    patchEngine: vi.fn().mockResolvedValue({ ...VIEW, active: "other" }),
    configureEngine: vi.fn().mockResolvedValue({ ...VIEW, active: "openai-api" }),
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

    await userEvent.selectOptions(select, "other");

    expect(theApi.patchEngine).toHaveBeenCalledWith("other");
    await waitFor(() => expect(select).toHaveValue("other"));
  });

  it("shows an error notice when switching fails", async () => {
    const theApi = api({ patchEngine: vi.fn().mockRejectedValue(new Error("no se pudo cambiar")) });
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "other");

    expect(await screen.findByText("no se pudo cambiar")).toBeInTheDocument();
  });

  it("disables the selector while busy", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={true} />);

    expect(await screen.findByRole("combobox")).toBeDisabled();
  });

  it("opens the credential form when selecting an unconfigured api_key profile", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "openai-api");

    expect(theApi.patchEngine).not.toHaveBeenCalled();
    expect(await screen.findByLabelText("Modelo")).toHaveValue("gpt-4");
    expect(screen.getByLabelText("API key")).toBeInTheDocument();
  });

  it("saves the credentials and updates the active engine", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "openai-api");
    const modelInput = await screen.findByLabelText("Modelo");
    await userEvent.clear(modelInput);
    await userEvent.type(modelInput, "gpt-4-turbo");
    await userEvent.type(screen.getByLabelText("API key"), "sk-secret");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    expect(theApi.configureEngine).toHaveBeenCalledWith("openai-api", "gpt-4-turbo", "sk-secret");
    await waitFor(() => expect(screen.queryByLabelText("API key")).not.toBeInTheDocument());
    await waitFor(() => expect(select).toHaveValue("openai-api"));
  });

  it("cancels the credential form without saving or changing the active engine", async () => {
    const theApi = api();
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "openai-api");
    await screen.findByLabelText("API key");
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(theApi.configureEngine).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    await waitFor(() => expect(select).toHaveValue("claude_sdk"));
  });

  it("shows an error notice when saving the credentials fails", async () => {
    const theApi = api({ configureEngine: vi.fn().mockRejectedValue(new Error("clave invalida")) });
    render(<EngineSelector api={theApi as never} busy={false} />);
    const select = await screen.findByRole("combobox");

    await userEvent.selectOptions(select, "openai-api");
    await userEvent.type(screen.getByLabelText("API key"), "sk-secret");
    await userEvent.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("clave invalida")).toBeInTheDocument();
  });
});
