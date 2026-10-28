import { useState, type KeyboardEvent } from "react";

import { SendIcon } from "./icons";

export const PLACEHOLDER = "Escribe a Jarvis…";
export const ANSWERING = "Jarvis está respondiendo…";

interface Props {
  disabled: boolean;
  /** Returning false means the text was not sent: the draft stays in the field. */
  onSend: (text: string) => boolean | void;
}

export function Composer({ disabled, onSend }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) {
      return;
    }
    if (onSend(trimmed) !== false) {
      setText("");
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        aria-label="Mensaje para Jarvis"
        placeholder={PLACEHOLDER}
        rows={2}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <button type="submit" aria-label="Enviar" disabled={disabled}>
        <SendIcon />
      </button>
      {disabled ? <span className="composer-status">{ANSWERING}</span> : null}
    </form>
  );
}
