import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "styles.css"), "utf-8");

function block(selector: RegExp): string {
  const match = css.match(selector);
  if (!match) {
    throw new Error(`no block for ${selector}`);
  }
  return match[0];
}

function variable(source: string, name: string): string {
  const match = source.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!match?.[1]) {
    throw new Error(`no ${name} in block`);
  }
  return match[1];
}

function luminance(hex: string): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

const theme = block(/:root \{[^}]*\}/);

describe("colour contrast (WCAG AA)", () => {
  it("has a single dark theme, independent of the system preference", () => {
    expect(css.match(/:root \{/g)).toHaveLength(1);
    expect(css).not.toContain("prefers-color-scheme");
    expect(theme).toContain("color-scheme: dark");
    expect(luminance(variable(theme, "--bg"))).toBeLessThan(0.01);
  });

  it("keeps fg, muted, warn and accent readable over bg and surface", () => {
    const bg = variable(theme, "--bg");
    const surface = variable(theme, "--surface");
    for (const name of ["--fg", "--muted", "--warn", "--accent"]) {
      expect(contrast(variable(theme, name), bg), `${name} on bg`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(variable(theme, name), surface), `${name} on surface`).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(variable(theme, "--accent-fg"), variable(theme, "--accent"))).toBeGreaterThanOrEqual(4.5);
  });

  it("declares focus rings and reduced motion", () => {
    expect(css).toContain(":focus-visible");
    expect(css).toContain("prefers-reduced-motion");
  });
});

describe("orb stage", () => {
  it("is fixed full-screen behind everything else", () => {
    const stage = block(/\.stage \{[^}]*\}/);

    expect(stage).toContain("position: fixed");
    expect(stage).toContain("inset: 0");
  });
});

describe("confirmation card", () => {
  it("is centred and fixed over the orb", () => {
    const confirmation = block(/\.confirmation \{[^}]*\}/);

    expect(confirmation).toContain("position: fixed");
    expect(confirmation).toContain("left: 50%");
  });
});

describe("agent colours", () => {
  it.each([
    ["--agent-jarvis", "#2F6FED"],
    ["--agent-viernes", "#2E9E5B"],
    ["--agent-edith", "#E0A100"],
  ])("declares %s as %s", (name, hex) => {
    expect(variable(theme, name).toUpperCase()).toBe(hex);
  });
});

describe("confirming orb", () => {
  it("adds an Edith-amber halo to the stage", () => {
    const halo = block(/\.stage\[data-orb-state="confirming"\][^{]*\{[^}]*\}/);

    expect(halo).toContain("var(--agent-edith)");
  });
});

describe("local resources only", () => {
  it("references no remote URL, font service or import", () => {
    expect(css).not.toMatch(/https?:\/\//);
    expect(css).not.toContain("fonts.googleapis.com");
    expect(css).not.toContain("@import");
    expect(css).not.toMatch(/url\(\s*["']?(?!data:)/);
  });
});
