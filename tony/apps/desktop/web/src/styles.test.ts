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

describe("PIN form", () => {
  it("stacks the field and the actions with a gap, so the focus ring never touches the buttons", () => {
    const form = block(/\.pin-form \{[^}]*\}/);

    expect(form).toContain("display: flex");
    expect(form).toContain("flex-direction: column");
    expect(form).toMatch(/gap:\s*0\.75rem/);
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

describe("visual themes", () => {
  const themeBlock = (id: string) => block(new RegExp(`\\n\\[data-theme="${id}"\\] \\{[^}]*\\}`));
  const THEMED_TOKENS = [
    "--bg", "--surface", "--fg", "--muted", "--accent", "--accent-fg", "--warn", "--border",
    "--glass", "--glass-strong", "--hairline", "--glow", "--holo-ink", "--accent-rgb", "--hot-rgb",
    "--deep-rgb", "--glow-rgb", "--warn-rgb", "--scrim", "--bg-art", "--radius", "--radius-sm",
    "--font-ui", "--font-display", "--agent-jarvis", "--agent-viernes", "--agent-edith",
  ];

  it("leaves holo as the :root default, with the extracted ink tokens equal to the old amber literals", () => {
    expect(theme).toMatch(/--accent-rgb:\s*255 179 71;/);
    expect(theme).toMatch(/--hot-rgb:\s*255 210 122;/);
    expect(theme).toMatch(/--deep-rgb:\s*255 140 26;/);
    expect(theme).toMatch(/--glow-rgb:\s*255 160 50;/);
    expect(theme).toMatch(/--warn-rgb:\s*255 143 128;/);
    expect(theme).toMatch(/--bg-art:\s*none;/);
  });

  it("no longer hard-codes amber outside the :root tokens", () => {
    const outsideRoot = css.replace(theme, "");
    for (const literal of ["255 179 71", "255 210 122", "255 160 50", "255 143 128", "255 140 26"]) {
      expect(outsideRoot, literal).not.toContain(literal);
    }
  });

  it.each(["aurora", "instrumento"])("%s overrides every token that makes up the look", (id) => {
    const source = themeBlock(id);
    for (const token of THEMED_TOKENS) {
      expect(source, `${id} ${token}`).toMatch(new RegExp(`${token}:`));
    }
  });

  it.each(["aurora", "instrumento"])("%s keeps text and accent readable (WCAG AA)", (id) => {
    const source = themeBlock(id);
    const bg = variable(source, "--bg");
    const surface = variable(source, "--surface");
    expect(luminance(bg)).toBeLessThan(0.05);
    for (const name of ["--fg", "--muted", "--warn", "--accent"]) {
      expect(contrast(variable(source, name), bg), `${id} ${name} on bg`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(variable(source, name), surface), `${id} ${name} on surface`).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(variable(source, "--accent-fg"), variable(source, "--accent"))).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps agent colours distinguishable per theme", () => {
    for (const id of ["aurora", "instrumento"]) {
      const source = themeBlock(id);
      const colours = ["--agent-jarvis", "--agent-viernes", "--agent-edith"].map((name) => variable(source, name));
      expect(new Set(colours).size).toBe(3);
    }
  });

  it("rounds the notched frames outside holo", () => {
    for (const id of ["aurora", "instrumento"]) {
      const frame = block(new RegExp(`\\[data-theme="${id}"\\] \\.holo-frame \\{[^}]*\\}`));
      expect(frame).toContain("clip-path: none");
      expect(frame).toContain("border-radius: var(--radius)");
    }
  });

  it("paints the page background art from the theme", () => {
    expect(block(/body \{[^}]*\}/)).toContain("background-image: var(--bg-art)");
    expect(block(/\.stage \{[^}]*\}/)).toContain("background-image: var(--bg-art)");
  });

  it("styles the appearance options with a visible focus ring and a swatch per theme", () => {
    expect(css).toMatch(/\.theme-option:has\(input:focus-visible\)/);
    for (const id of ["holo", "aurora", "instrumento"]) {
      expect(css).toContain(`.theme-swatch[data-theme="${id}"]`);
    }
  });
});

describe("HUD device selects", () => {
  const rule = (selector: string) => block(new RegExp(`(^|\\n)${selector.replace(/[.*:()\[\]"=-]/g, "\\$&")} \\{[^}]*\\}`));

  it("lets the shared frame draw the outline, so the select itself is bare accent text", () => {
    const select = rule(".select-frame select");

    expect(select).toContain("appearance: none");
    expect(select).toContain("background: transparent");
    expect(select).toContain("border: none");
    expect(select).toContain("color: var(--accent)");
    expect(select).toContain("font-family: var(--font-ui)");
    expect(css.match(/clip-path: polygon\(/g)).toHaveLength(2);
  });

  it("draws a visible accent arrow that never steals the click", () => {
    const arrow = rule(".select-frame::after");

    expect(arrow).toContain("content: \"\"");
    expect(arrow).toContain("pointer-events: none");
    expect(arrow).toContain("var(--accent)");
  });

  it("keeps the option list readable: dark surface, light text", () => {
    const option = rule(".select-frame option");

    expect(option).toContain("background: var(--surface)");
    expect(option).toContain("color: var(--fg)");
  });

  it("drops the old amber-bordered box", () => {
    expect(css).not.toMatch(/\.audio-settings-card select \{/);
  });

  it("uses the small radius in the rounded themes instead of the button pill", () => {
    const rounded = rule(':is([data-theme="aurora"], [data-theme="instrumento"]) .select-frame');

    expect(rounded).toContain("border-radius: var(--radius-sm)");
  });
});
