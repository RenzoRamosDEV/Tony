import { useEffect, useRef } from "react";

import type { Command, ConfirmDecision, NeedsConfirmationEvent } from "../bridge/types";

interface Props {
  confirmation: NeedsConfirmationEvent;
  onAnswer: (command: Command) => void;
  /** Changes whenever the window asks to put the focus back on the safe option. */
  focusRequest: number;
}

export function ConfirmationCard({ confirmation, onAnswer, focusRequest }: Props) {
  const deny = useRef<HTMLButtonElement>(null);
  const answer = (decision: ConfirmDecision) =>
    onAnswer({ type: "confirm", task_id: confirmation.task_id, decision });

  useEffect(() => {
    deny.current?.focus();
  }, [confirmation.task_id, focusRequest]);

  return (
    <section className="confirmation hud-panel" aria-labelledby="confirmation-title">
      <h2 id="confirmation-title">Edith · confirmación</h2>
      <p>{confirmation.question}</p>
      <p>
        <code className="tool-name">{confirmation.tool}</code>
      </p>
      <pre className="args">{confirmation.args_preview}</pre>
      <div className="confirmation-actions">
        <button type="button" onClick={() => answer("allow")}>
          Permitir
        </button>
        <button ref={deny} type="button" className="secondary" onClick={() => answer("deny")}>
          Denegar
        </button>
        {confirmation.allow_always ? (
          <button type="button" className="secondary" onClick={() => answer("always")}>
            Permitir siempre
          </button>
        ) : null}
      </div>
    </section>
  );
}
