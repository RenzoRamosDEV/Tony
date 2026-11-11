import type { Command } from "../bridge/types";
import type { PinView } from "../state/reducer";

interface Props {
  pin: PinView;
  onCommand: (command: Command) => void;
  onUnlockRequest: () => void;
}

function SessionControl({ pin, onCommand, onUnlockRequest }: Props) {
  if (pin.reason === null) {
    return null;
  }
  if (pin.reason === "no_lock_file" || pin.reason === "not_required") {
    return <p>No hay PIN configurado. Ejecute `tony pin set` en una terminal para crearlo.</p>;
  }
  const [status, action, onClick] = pin.canUnlock
    ? ["Bloqueada", "Introducir PIN", onUnlockRequest]
    : ["Desbloqueada", "Bloquear", () => onCommand({ type: "lock" })];
  return (
    <div className="edith-session">
      <span role="status">{status}</span>
      <button type="button" className="holo-frame holo" onClick={onClick}>
        {action}
      </button>
    </div>
  );
}

export function EdithSection(props: Props) {
  return (
    <div role="group" aria-labelledby="edith-section-title" className="edith-section">
      <h3 id="edith-section-title" className="holo">
        Edith
      </h3>
      <SessionControl {...props} />
    </div>
  );
}
