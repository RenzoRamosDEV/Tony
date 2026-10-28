import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Message } from "../protocol/reducer";
import { TranscriptDrawer } from "./TranscriptDrawer";

const MESSAGES: Message[] = [
  { id: "1", role: "user", content: "uno", seq: 1, effectiveMode: "text" },
  { id: "2", role: "assistant", content: "dos", seq: 2 },
  { id: "3", role: "user", content: "tres", seq: 3, effectiveMode: "voice" },
  { id: "4", role: "assistant", content: "cuatro", seq: 4 },
  { id: "5", role: "user", content: "cinco", seq: 5 },
];

function toggle(): HTMLElement {
  return screen.getByRole("button", { name: /transcripción/ });
}

describe("TranscriptDrawer", () => {
  it("starts collapsed", () => {
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Transcripción" })).toBeNull();
  });

  it("opens with the whole conversation and its mode labels", async () => {
    const user = userEvent.setup();
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);

    await user.click(toggle());

    const drawer = screen.getByRole("region", { name: "Transcripción" });
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(drawer.querySelectorAll("article")).toHaveLength(5);
    expect(drawer).toHaveTextContent("voice");
    expect(drawer).toHaveTextContent("text");
  });

  it("does not announce messages: the subtitles already do", async () => {
    const user = userEvent.setup();
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);

    await user.click(toggle());

    expect(screen.getByRole("region", { name: "Transcripción" }).querySelector("[aria-live]")).toBeNull();
  });

  it("closes with Escape and gives the focus back to the toggle", async () => {
    const user = userEvent.setup();
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);
    await user.click(toggle());
    await user.tab();

    await user.keyboard("{Escape}");

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(toggle()).toHaveFocus();
    expect(screen.queryByRole("region", { name: "Transcripción" })).toBeNull();
  });

  it("closes with the toggle", async () => {
    const user = userEvent.setup();
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);

    await user.click(toggle());
    await user.click(toggle());

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("Escape does nothing while closed", async () => {
    const user = userEvent.setup();
    render(<TranscriptDrawer messages={MESSAGES} waitText={null} />);

    await user.keyboard("{Escape}");

    expect(toggle()).not.toHaveFocus();
  });
});
