import { useEffect, useRef, useState } from "react";

import type { Message } from "../protocol/reducer";

interface Props {
  messages: Message[];
  turnInProgress: boolean;
  onSend: (text: string) => void;
}

export function ChatPanel({ messages, turnInProgress, onSend }: Props) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) {
      list.scrollTop = list.scrollHeight;
    }
  }, [messages]);

  const submit = () => {
    const trimmed = text.trim();
    if (trimmed === "" || turnInProgress) {
      return;
    }
    onSend(trimmed);
    setText("");
  };

  return (
    <section className="chat-overlay" aria-label="Chat">
      <ul className="chat-lines" ref={listRef}>
        {messages.length === 0 ? (
          <li className="chat-empty">La conversación aparece aquí, hablada o escrita.</li>
        ) : (
          messages.map((message) => (
            <li key={message.id} className={`chat-line chat-line-${message.role}`}>
              <span className="chat-speaker">{message.role === "assistant" ? "JARVIS" : "RENZO"}:</span>{" "}
              {message.content}
            </li>
          ))
        )}
      </ul>
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <input
          type="text"
          aria-label="Mensaje"
          placeholder="Escribe…"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <button type="submit" className="holo" disabled={turnInProgress || text.trim() === ""}>
          Enviar
        </button>
      </form>
    </section>
  );
}
