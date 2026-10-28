import { useEffect, useState } from "react";

import { createApi } from "../api/client";
import { REPLY_MODES, type ReplyMode } from "../protocol/types";

interface Props {
  value: ReplyMode;
  onChanged: (mode: ReplyMode) => void;
  fetchImpl?: typeof fetch;
}

export function ModeSelector({ value, onChanged, fetchImpl }: Props) {
  const [active, setActive] = useState<ReplyMode>(value);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setActive(value);
  }, [value]);

  const choose = async (mode: ReplyMode) => {
    const previous = active;
    setActive(mode);
    setError(null);
    try {
      const settings = await createApi(fetchImpl).patchSettings(mode);
      setActive(settings.reply_mode);
      onChanged(settings.reply_mode);
    } catch (failure) {
      setActive(previous);
      setError(failure instanceof Error ? failure.message : "No se pudo cambiar el modo");
    }
  };

  return (
    <div className="mode-selector">
      <div role="radiogroup" aria-label="Modo de respuesta" className="mode-group">
        {REPLY_MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-label={mode}
            aria-checked={active === mode}
            className={active === mode ? "mode active" : "mode"}
            onClick={() => void choose(mode)}
          >
            {mode}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="warn">
          {error}
        </p>
      ) : null}
    </div>
  );
}
