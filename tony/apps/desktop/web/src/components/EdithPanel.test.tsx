import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AuditRow } from "../bridge/types";
import { EdithPanel } from "./EdithPanel";

const ROWS: AuditRow[] = [
  { time: "09:00:00", agent: "viernes", tool: "filesystem.read_file", verdict: "allow", rule: "r/allow", user_decision: null },
  { time: "09:00:01", agent: "viernes", tool: "shell.run", verdict: "deny", rule: "r/deny", user_decision: null },
  { time: "09:00:02", agent: "viernes", tool: "filesystem.delete_file", verdict: "confirm", rule: "r/c", user_decision: "allow" },
];

describe("EdithPanel", () => {
  it("lists time, agent, tool, verdict, rule and user decision", () => {
    render(<EdithPanel rows={ROWS.slice(2)} filter="all" onFilter={vi.fn()} />);

    const cells = screen.getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells).toEqual(["09:00:02", "viernes", "filesystem.delete_file", "confirm", "r/c", "allow"]);
  });

  it("shows the given rows only", () => {
    render(<EdithPanel rows={ROWS.slice(1, 2)} filter="deny" onFilter={vi.fn()} />);

    expect(screen.getByText("shell.run")).toBeInTheDocument();
    expect(screen.queryByText("filesystem.read_file")).toBeNull();
  });

  it("selects the verdict filter", async () => {
    const onFilter = vi.fn();
    render(<EdithPanel rows={ROWS} filter="all" onFilter={onFilter} />);
    const select = screen.getByRole("combobox", { name: "Veredicto" });

    expect((screen.getAllByRole("option") as HTMLOptionElement[]).map((o) => o.value)).toEqual([
      "all",
      "allow",
      "confirm",
      "deny",
    ]);
    await userEvent.selectOptions(select, "deny");

    expect(onFilter.mock.calls).toEqual([["deny"]]);
  });

  it("collapsing and expanding keeps the rows", async () => {
    render(<EdithPanel rows={ROWS} filter="all" onFilter={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /Edith/ });

    await userEvent.click(toggle);
    expect(screen.getByText("shell.run")).not.toBeVisible();
    await userEvent.click(toggle);

    expect(screen.getByText("shell.run")).toBeVisible();
  });
});
