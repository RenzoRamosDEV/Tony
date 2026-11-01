import DOMPurify from "dompurify";
import { Marked } from "marked";

const FORBID_TAGS = ["style", "iframe", "object", "embed", "form", "input", "img", "svg"];
const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char);
}

const markdown = new Marked({
  async: false,
  gfm: true,
  breaks: true,
  renderer: {
    html: ({ text }) => escapeHtml(text),
  },
});

// Links stay main-frame clicks so the desktop page hands them to the system browser.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("rel", "noopener noreferrer");
    node.removeAttribute("target");
  }
});

/** Markdown to HTML: raw HTML is shown as text, then DOMPurify strips anything unsafe left. */
export function renderMarkdown(text: string): string {
  if (!text) {
    return "";
  }
  const html = markdown.parse(text, { async: false });
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true }, FORBID_TAGS });
}
