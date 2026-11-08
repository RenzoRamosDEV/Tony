import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TaskNode } from "../state/reducer";
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

describe("ActivityPanel", () => {
  it("shows tasks with their calls and subagents, but not the generated summary", () => {
    render(<ActivityPanel tasks={[TASK]} />);

    expect(screen.getByText("viernes: leer notas")).toBeVisible();
    expect(screen.getByText("filesystem.read_file — allow")).toBeVisible();
    expect(screen.getByText("lector")).toBeVisible();
    expect(screen.getByText("b — deny")).toBeVisible();
    expect(screen.queryByText("en curso")).not.toBeInTheDocument();
  });

  it("shows the most recently started task first", () => {
    const older: TaskNode = { ...TASK, task_id: "t0", label: "viernes: tarea vieja" };
    const newer: TaskNode = { ...TASK, task_id: "t2", label: "viernes: tarea nueva" };
    render(<ActivityPanel tasks={[older, newer]} />);

    const labels = screen.getAllByText(/viernes: tarea/).map((el) => el.textContent);
    expect(labels).toEqual(["viernes: tarea nueva", "viernes: tarea vieja"]);
  });

  it("shows a placeholder when there are no delegated tasks", () => {
    render(<ActivityPanel tasks={[]} />);

    expect(screen.getByText("Sin tareas delegadas.")).toBeVisible();
  });

  it("collapsing and expanding keeps the content", async () => {
    render(<ActivityPanel tasks={[TASK]} />);
    const toggle = screen.getByRole("button", { name: /Actividad/ });

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("viernes: leer notas")).not.toBeVisible();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("viernes: leer notas")).toBeVisible();
  });
});
