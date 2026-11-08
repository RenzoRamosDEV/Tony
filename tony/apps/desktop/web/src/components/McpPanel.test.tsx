import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ServerRow } from "../state/reducer";
import { McpPanel } from "./McpPanel";

const SERVERS: ServerRow[] = [
  { agent: "viernes", server: "filesystem", down: false, label: "Viernes - File System - MCP" },
  { agent: "viernes", server: "shell", down: true, label: "Viernes - Shell - MCP" },
];

describe("McpPanel", () => {
  it("shows a down MCP server in red", () => {
    render(<McpPanel servers={SERVERS} />);

    expect(screen.getByText("Viernes - Shell - MCP")).toHaveStyle({ color: "#D93025" });
    expect(screen.getByText("Viernes - File System - MCP")).not.toHaveStyle({ color: "#D93025" });
  });

  it("shows an info button with a short tooltip of what the MCP server does", () => {
    render(<McpPanel servers={SERVERS} />);

    expect(
      screen.getByTitle("Lee y escribe archivos en las carpetas de notas permitidas."),
    ).toBeVisible();
  });

  it("shows a placeholder when there are no servers connected", () => {
    render(<McpPanel servers={[]} />);

    expect(screen.getByText("Sin servidores conectados.")).toBeVisible();
  });
});
