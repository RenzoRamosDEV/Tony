import { useEffect, useRef, useState } from "react";

import type { Message } from "../protocol/reducer";
import { ChatList } from "./ChatList";
import { TranscriptIcon } from "./icons";

interface Props {
  messages: Message[];
  waitText: string | null;
}

export function TranscriptDrawer({ messages, waitText }: Props) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggle.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      <button
        ref={toggle}
        type="button"
        className="icon"
        aria-label={open ? "Ocultar transcripción" : "Mostrar transcripción"}
        aria-expanded={open}
        aria-controls="transcript"
        onClick={() => setOpen((value) => !value)}
      >
        <TranscriptIcon />
      </button>
      {open ? (
        <section id="transcript" className="transcript hud-panel" aria-label="Transcripción">
          <ChatList messages={messages} waitText={waitText} live={false} />
        </section>
      ) : null}
    </>
  );
}
