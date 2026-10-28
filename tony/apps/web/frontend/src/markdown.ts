import DOMPurify from "dompurify";
import { marked } from "marked";

const FORBID_TAGS = ["style", "iframe", "object", "embed", "form", "input", "img", "svg"];

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("rel", "noopener noreferrer");
    node.setAttribute("target", "_blank");
  }
});

/** Markdown to HTML with every raw tag, script and unsafe URL stripped. */
export function renderMarkdown(text: string): string {
  if (!text) {
    return "";
  }
  const html = marked.parse(text, { async: false, gfm: true, breaks: true });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS,
    ADD_ATTR: ["target"],
  });
}
