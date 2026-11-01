import { describe, expect, it } from "vitest";

import { renderMarkdown } from "./markdown";

function parse(html: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

describe("renderMarkdown", () => {
  it("neutralises raw HTML and keeps the markdown emphasis", () => {
    const html = parse(renderMarkdown("Hola <img src=x onerror=alert(1)> **ok**"));

    expect(html.querySelector("img")).toBeNull();
    expect(html.querySelector("[onerror]")).toBeNull();
    expect(html.querySelector("strong")?.textContent).toBe("ok");
    expect(html.textContent).toContain("Hola");
  });

  it("escapes raw HTML as visible text instead of dropping it", () => {
    const rendered = renderMarkdown("<script>alert(1)</script>");
    const html = parse(rendered);

    expect(rendered).toContain("&lt;script&gt;");
    expect(html.querySelector("script")).toBeNull();
    expect(html.textContent).toContain("<script>alert(1)</script>");
  });

  it("keeps links in the page frame without leaking the opener", () => {
    const html = parse(renderMarkdown("[docs](https://example.com)"));
    const link = html.querySelector("a");

    expect(link?.getAttribute("href")).toBe("https://example.com");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link?.hasAttribute("target")).toBe(false);
  });

  it("preserves code blocks and inline code", () => {
    const html = parse(renderMarkdown("```python\nprint('hola')\n```\n\ny `x`"));

    expect(html.querySelector("pre code")?.textContent).toBe("print('hola')\n");
    expect(html.querySelectorAll("code")).toHaveLength(2);
  });

  it("renders pipe tables", () => {
    const html = parse(renderMarkdown("| a | b |\n|---|---|\n| 1 | 2 |"));

    expect(html.querySelector("table")).not.toBeNull();
    expect(html.querySelectorAll("td")).toHaveLength(2);
  });

  it("removes scripts, styles and javascript urls", () => {
    const html = parse(
      renderMarkdown('<script>alert(1)</script><style>body{}</style>[x](javascript:alert(1))'),
    );

    expect(html.querySelector("script")).toBeNull();
    expect(html.querySelector("style")).toBeNull();
    expect(html.querySelector("a")?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it("renders an empty string to an empty string", () => {
    expect(renderMarkdown("")).toBe("");
  });
});
