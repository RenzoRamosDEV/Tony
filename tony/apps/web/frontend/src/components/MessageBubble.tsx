import { useMemo } from "react";

import { renderMarkdown } from "../markdown";
import type { Message } from "../protocol/reducer";
import { MicIcon } from "./icons";

export function MessageBubble({ message }: { message: Message }) {
  const html = useMemo(
    () => (message.role === "assistant" ? renderMarkdown(message.content) : ""),
    [message.role, message.content],
  );
  const spoken = message.source === "voice";
  const label = message.role === "user" ? (spoken ? "Mensaje tuyo por voz" : "Mensaje tuyo") : "Respuesta de Jarvis";
  return (
    <article
      className={`bubble ${message.role}`}
      data-role={message.role}
      data-source={spoken ? "voice" : undefined}
      data-streaming={message.streaming ? "true" : undefined}
      aria-label={label}
    >
      {message.role === "assistant" ? (
        <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <p className="plain">
          {spoken ? (
            <span className="source" title="Transcrito del micrófono">
              <MicIcon width={14} height={14} />
            </span>
          ) : null}
          {message.content}
        </p>
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
