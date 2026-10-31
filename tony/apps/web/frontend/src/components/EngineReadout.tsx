import { useEffect, useState } from "react";

import { createApi, type EnginesView } from "../api/client";

interface Props {
  disabled: boolean;
  fetchImpl?: typeof fetch;
  onBusy?: (busy: boolean) => void;
}

export function EngineReadout({ disabled, fetchImpl, onBusy }: Props) {
  const [view, setView] = useState<EnginesView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = createApi(fetchImpl);
    let cancelled = false;
    api
      .getEngines()
      .then((value) => {
        if (!cancelled) setView(value);
      })
      .catch(() => {
        if (!cancelled) setError("motor: sin datos");
      });
    return () => {
      cancelled = true;
    };
  }, [fetchImpl]);

  const choose = async (profile: string) => {
    if (disabled || profile === view?.active) return;
    onBusy?.(true);
    setError(null);
    try {
      setView(await createApi(fetchImpl).patchEngine(profile));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "no se pudo cambiar");
    } finally {
      onBusy?.(false);
    }
  };

  return (
    <label className="hud-field">
      <span className="hud-label">Motor</span>
      <select
        aria-label="Motor"
        className="hud-value"
        value={view?.active ?? ""}
        disabled={disabled || view === null}
        onChange={(event) => void choose(event.target.value)}
      >
        {view === null ? (
          <option value="">· · ·</option>
        ) : (
          view.profiles.map((profile) => (
            <option key={profile.name} value={profile.name}>
              {profile.name}
            </option>
          ))
        )}
      </select>
      {error ? <span className="hud-error">{error}</span> : null}
    </label>
  );
}
