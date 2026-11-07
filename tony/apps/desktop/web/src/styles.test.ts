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

describe("holo frame shared by buttons and side cards", () => {
  const frame = () => block(/\.holo-frame \{[^}]*\}/);
  const holo = () => block(/\.holo \{[^}]*\}/);
  const sidePanel = () => block(/\.side-panel \{[^}]*\}/);

  it("owns the square, notched outline and the button background", () => {
    expect(frame()).toContain("border-radius: 0");
    expect(frame()).toContain("clip-path: polygon(");
    expect(frame()).toContain("background: rgb(5 7 10 / 0.3)");
    expect(frame()).toMatch(/--cut:\s*8px/);
  });

  it("defines the outline once, so the button only adds typography", () => {
    expect(css.match(/clip-path: polygon\(/g)).toHaveLength(2);
    expect(holo()).not.toContain("clip-path");
    expect(css).not.toMatch(/\.holo::before/);
  });

  it("scales the notch up for the larger side cards and keeps them interactive", () => {
    const cut = sidePanel().match(/--cut:\s*(\d+)px/);

    expect(Number(cut?.[1])).toBeGreaterThan(8);
    expect(sidePanel()).toContain("pointer-events: auto");
  });
});

describe("HUD scrollbars", () => {
  const rule = (selector: string) => block(new RegExp(`(^|\\n)${selector.replace(/[.*:()-]/g, "\\$&")} \\{[^}]*\\}`));

  it("shares one amber ink token between frame edges and scrollbar thumbs", () => {
    expect(theme).toMatch(/--holo-ink:\s*255 157 46;/);
    expect(rule(".holo-frame::before")).toContain("background: rgb(var(--holo-ink) / 0.55)");
    expect(css).not.toContain("255 157 46 /");
  });

  it("is thin, square and has a transparent track, no arrows and no corner on every scroller", () => {
    const bar = rule("::-webkit-scrollbar");
    expect(bar).toContain("width: 6px");
    expect(bar).toContain("height: 6px");
    expect(rule("::-webkit-scrollbar-track")).toContain("background: transparent");
    expect(rule("::-webkit-scrollbar-corner")).toContain("background: transparent");
    expect(rule("::-webkit-scrollbar-button")).toContain("display: none");
    expect(rule("::-webkit-scrollbar-thumb")).toContain("border-radius: 0");
  });

  it("dims the thumb at rest and brightens it on hover", () => {
    const alpha = (selector: string) =>
      Number(rule(selector).match(/background: rgb\(var\(--holo-ink\) \/ ([\d.]+)\)/)?.[1]);
    const rest = alpha("::-webkit-scrollbar-thumb");
    const hover = alpha("::-webkit-scrollbar-thumb:hover");

    expect(rest).toBeGreaterThan(0);
    expect(rest).toBeLessThan(0.55);
    expect(hover).toBeGreaterThan(rest);
  });

  it("styles scrollers globally, not per element", () => {
    expect(css).not.toMatch(/[\w\]]::-webkit-scrollbar/);
    expect(css.match(/scrollbar-width:/g)).toHaveLength(1);
    expect(css.match(/scrollbar-color:/g)).toHaveLength(1);
  });

  it("keeps the standard properties out of Chromium so they do not override the webkit styling", () => {
    const standard = block(/@supports not selector\(::-webkit-scrollbar\) \{[\s\S]*?\n\}/);

    expect(standard).toContain("scrollbar-width: thin");
    expect(standard).toContain("scrollbar-color: rgb(var(--holo-ink) / 0.4) transparent");
  });
});
