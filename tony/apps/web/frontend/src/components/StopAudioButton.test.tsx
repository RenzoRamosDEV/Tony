import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StopAudioButton } from "./StopAudioButton";

describe("StopAudioButton", () => {
  it("renders nothing unless something is being spoken", () => {
    render(<StopAudioButton visible={false} onStop={() => undefined} />);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows 'Detener audio' and calls onStop", async () => {
    const onStop = vi.fn();
    render(<StopAudioButton visible onStop={onStop} />);

    await userEvent.click(screen.getByRole("button", { name: "Detener audio" }));

    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
