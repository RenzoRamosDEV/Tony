import { useEffect, useRef, useState } from "react";

import { renderMarkdown } from "../markdown";
import type { ChatMessage } from "../state/reducer";

interface Props {
  messages: ChatMessage[];
  onSend: (text: string) => void;
}

function MessageText({ message }: { message: ChatMessage }) {
  if (message.kind !== "agent") {
    return <span className="chat-text">{message.text}</span>;
  }
  return <div className="chat-text markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.text) }} />;
}

export function ChatPanel({ messages, onSend }: Props) {
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
    if (trimmed === "") {
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
            <li key={message.id} className={`chat-line chat-line-${message.kind}`}>
              <span className="chat-speaker" style={{ color: message.colour }}>
                {message.label}:
              </span>{" "}
              <MessageText message={message} />
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
        <button type="submit" className="holo" disabled={text.trim() === ""}>
          Enviar
        </button>
      </form>
    </section>
  );
}
