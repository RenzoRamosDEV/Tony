import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ServerRow, TaskNode } from "../state/reducer";
import { ActivityPanel } from "./ActivityPanel";

const TASK: TaskNode = {
  task_id: "t1",
  agent: "viernes",
  objetivo: "leer notas",
  label: "viernes: leer notas",
  calls: [{ tool: "filesystem.read_file", verdict: "allow", user_decision: null, label: "filesystem.read_file — allow" }],
  subagents: [{ name: "lector", calls: [{ tool: "b", verdict: "deny", user_decision: null, label: "b — deny" }] }],
  summary: "en curso",
};
const SERVERS: ServerRow[] = [
  { agent: "viernes", server: "filesystem", down: false, label: "viernes/filesystem — activo" },
  { agent: "viernes", server: "shell", down: true, label: "viernes/shell — caído: x" },
];

describe("ActivityPanel", () => {
  it("shows tasks with their calls, subagents and summary", () => {
    render(<ActivityPanel tasks={[TASK]} servers={[]} />);

    expect(screen.getByText("viernes: leer notas")).toBeVisible();
    expect(screen.getByText("filesystem.read_file — allow")).toBeVisible();
    expect(screen.getByText("lector")).toBeVisible();
    expect(screen.getByText("b — deny")).toBeVisible();
    expect(screen.getByText("en curso")).toBeVisible();
  });

  it("shows a down MCP server in red", () => {
    render(<ActivityPanel tasks={[]} servers={SERVERS} />);

    expect(screen.getByText("viernes/shell — caído: x")).toHaveStyle({ color: "#D93025" });
    expect(screen.getByText("viernes/filesystem — activo")).not.toHaveStyle({ color: "#D93025" });
  });

  it("collapsing and expanding keeps the content", async () => {
    render(<ActivityPanel tasks={[TASK]} servers={[]} />);
    const toggle = screen.getByRole("button", { name: /Actividad/ });

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("viernes: leer notas")).not.toBeVisible();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("viernes: leer notas")).toBeVisible();
  });
});
