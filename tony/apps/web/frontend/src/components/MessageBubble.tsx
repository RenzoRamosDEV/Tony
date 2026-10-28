import { useMemo } from "react";

import { renderMarkdown } from "../markdown";
import type { Message } from "../protocol/reducer";

export function MessageBubble({ message }: { message: Message }) {
  const html = useMemo(
    () => (message.role === "assistant" ? renderMarkdown(message.content) : ""),
    [message.role, message.content],
  );
  const label = message.role === "user" ? "Mensaje tuyo" : "Respuesta de Jarvis";
  return (
    <article
      className={`bubble ${message.role}`}
      data-role={message.role}
      data-streaming={message.streaming ? "true" : undefined}
      aria-label={label}
    >
      {message.role === "assistant" ? (
        <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <p className="plain">{message.content}</p>
      )}
      {message.role === "user" && message.effectiveMode ? (
        <span className="mode-badge" title="Modo de respuesta efectivo">
          {message.effectiveMode}
        </span>
      ) : null}
    </article>
  );
}

export function WaitBubble({ text }: { text: string }) {
  return (
    <div className="bubble wait" data-role="wait">
      <p className="plain">{text}</p>
    </div>
  );
}
