import { useMemo } from "react";

import type { Message } from "../protocol/reducer";
import { EMPTY_STATE } from "./ChatList";
import { MessageBubble, WaitBubble } from "./MessageBubble";

interface Props {
  messages: Message[];
  waitText: string | null;
}

/** The last question and the reply that follows it; an older reply never answers a newer question. */
function lastExchange(messages: Message[]): { question: Message | null; reply: Message | null } {
  let questionIndex = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]!.role === "user") {
      questionIndex = i;
      break;
    }
  }
  let reply: Message | null = null;
  for (let i = messages.length - 1; i > questionIndex; i -= 1) {
    if (messages[i]!.role === "assistant") {
      reply = messages[i]!;
      break;
    }
  }
  return { question: questionIndex >= 0 ? messages[questionIndex]! : null, reply };
}

export function Subtitles({ messages, waitText }: Props) {
  const { question, reply } = useMemo(() => lastExchange(messages), [messages]);
  const empty = question === null && reply === null && waitText === null;
  return (
    <section className="subtitles hud-panel" aria-live="polite" aria-label="Subtítulos">
      {empty ? <p className="empty muted">{EMPTY_STATE}</p> : null}
      {question ? <MessageBubble message={question} /> : null}
      {waitText !== null ? <WaitBubble text={waitText} /> : reply ? <MessageBubble message={reply} /> : null}
    </section>
  );
}
