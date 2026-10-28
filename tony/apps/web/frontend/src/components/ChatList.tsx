import { useEffect, useRef } from "react";

import type { Message } from "../protocol/reducer";
import { MessageBubble, WaitBubble } from "./MessageBubble";

interface Props {
  messages: Message[];
  waitText: string | null;
  /** Only one region may announce new messages; the subtitles do it in the HUD. */
  live?: boolean;
}

export const EMPTY_STATE = "Escribe a Jarvis…";

export function ChatList({ messages, waitText, live = true }: Props) {
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages, waitText]);

  return (
    <section className="chat-list" aria-live={live ? "polite" : undefined} aria-label="Conversación">
      {messages.length === 0 && waitText === null ? (
        <p className="empty muted">{EMPTY_STATE}</p>
      ) : null}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {waitText !== null ? <WaitBubble text={waitText} /> : null}
      <div ref={end} />
    </section>
  );
}
