import { CloseIcon } from "./icons";

export const DISCONNECTED = "Desconectado, reintentando…";

interface Props {
  connected: boolean;
  notice: string | null;
  onDismiss: () => void;
}

export function StatusBanner({ connected, notice, onDismiss }: Props) {
  if (connected && notice === null) {
    return null;
  }
  return (
    <div className="banners">
      {!connected ? (
        <p role="status" className="banner muted">
          {DISCONNECTED}
        </p>
      ) : null}
      {notice !== null ? (
        <p role="alert" className="banner warn">
          <span>{notice}</span>
          <button type="button" aria-label="Cerrar aviso" className="icon" onClick={onDismiss}>
            <CloseIcon />
          </button>
        </p>
      ) : null}
    </div>
  );
}
