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

const light = block(/:root \{[^}]*\}/);
const dark = block(/@media \(prefers-color-scheme: dark\) \{\s*:root \{[^}]*\}/);

describe("colour contrast (WCAG AA)", () => {
  it.each([
    ["light", light],
    ["dark", dark],
  ])("%s theme keeps fg, muted and warn readable over bg and surface", (_name, theme) => {
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
    expect(css).toContain("max-width: 80ch");
  });
});
