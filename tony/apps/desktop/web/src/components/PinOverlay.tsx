import { useEffect, useRef, useState } from "react";

import type { Command } from "../bridge/types";
import type { PinView } from "../state/reducer";

const TICK_MS = 250;

interface Props {
  pin: PinView;
  onCommand: (command: Command) => void;
  onHide: () => void;
  onUnlockRequest: () => void;
}

function secondsLeft(retryAt: number): number {
  return Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
}

function useCountdown(retryAt: number): number {
  const [left, setLeft] = useState(() => secondsLeft(retryAt));
  useEffect(() => {
    setLeft(secondsLeft(retryAt));
    if (secondsLeft(retryAt) === 0) {
      return;
    }
    const timer = setInterval(() => {
      const next = secondsLeft(retryAt);
      setLeft(next);
      if (next === 0) {
        clearInterval(timer);
      }
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [retryAt]);
  return left;
}

/** The PIN lives only in the uncontrolled field until it is sent once, then the field is cleared. */
function PinPrompt({ pin, onCommand, onHide }: Omit<Props, "onUnlockRequest">) {
  const field = useRef<HTMLInputElement>(null);
  const left = useCountdown(pin.retryAt);

  useEffect(() => {
    if (left === 0) {
      field.current?.focus();
    }
  }, [left]);

  const submit = () => {
    const input = field.current;
    if (input === null || input.value === "" || left > 0) {
      return;
    }
    onCommand({ type: "unlock", pin: input.value });
    input.value = "";
  };

  return (
    <form
      className="pin-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label>
        PIN
        <input ref={field} type="password" autoComplete="off" inputMode="numeric" disabled={left > 0} />
      </label>
      {left > 0 ? (
        <p className="warn" role="status">
          Espere {left} s
        </p>
      ) : null}
      <div className="confirmation-actions">
        <button type="submit" className="holo-frame holo" disabled={left > 0}>
          Desbloquear
        </button>
        <button
          type="button"
          className="holo-frame holo"
          onClick={() => {
            onCommand({ type: "unlock", pin: null });
            onHide();
          }}
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}

export function PinOverlay({ pin, onCommand, onHide, onUnlockRequest }: Props) {
  if (pin.mode === "hidden") {
    return pin.canUnlock ? (
      <button type="button" className="unlock-control holo-frame holo" onClick={onUnlockRequest}>
        Introducir PIN
      </button>
    ) : null;
  }
  return (
    <div className="pin-overlay">
      <section role="dialog" aria-modal="true" aria-labelledby="pin-title" className="pin-card holo-frame">
        <h2 id="pin-title" className="holo">
          Edith · PIN
        </h2>
        <p>{pin.message}</p>
        {pin.mode === "prompt" ? (
          <PinPrompt pin={pin} onCommand={onCommand} onHide={onHide} />
        ) : (
          <button type="button" className="secondary" onClick={onHide}>
            Entendido
          </button>
        )}
      </section>
    </div>
  );
}
