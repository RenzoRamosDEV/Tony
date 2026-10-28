import { useEffect, useState } from "react";

import { EXPIRED_NOTICE, type PendingConfirmation } from "../protocol/reducer";

interface Props {
  confirmation: PendingConfirmation;
  onAnswer: (confirmationId: string, approved: boolean) => void;
}

function remainingSeconds(deadline: number): number {
  return Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
}

export function ConfirmationCard({ confirmation, onAnswer }: Props) {
  const [remaining, setRemaining] = useState(() => remainingSeconds(confirmation.deadline));

  useEffect(() => {
    setRemaining(remainingSeconds(confirmation.deadline));
    const timer = setInterval(() => setRemaining(remainingSeconds(confirmation.deadline)), 1000);
    return () => clearInterval(timer);
  }, [confirmation.deadline]);

  return (
    <section className="confirmation" aria-labelledby="confirmation-title">
      <h2 id="confirmation-title">Confirmación requerida</h2>
      <p>
        Viernes quiere ejecutar <code className="tool-name">{confirmation.tool}</code>
      </p>
      <pre className="args">{JSON.stringify(confirmation.args, null, 2)}</pre>
      {remaining > 0 ? (
        <div className="confirmation-actions">
          <button type="button" onClick={() => onAnswer(confirmation.confirmationId, true)}>
            Confirmar
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => onAnswer(confirmation.confirmationId, false)}
          >
            Rechazar
          </button>
          <span className="countdown" aria-live="off">
            Caduca en {remaining} s
          </span>
        </div>
      ) : (
        <p role="status" className="warn">
          {EXPIRED_NOTICE}
        </p>
      )}
    </section>
  );
}
