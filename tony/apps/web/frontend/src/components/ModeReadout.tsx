import { useEffect, useState } from "react";

import { createApi } from "../api/client";
import { REPLY_MODES, type ReplyMode } from "../protocol/types";

const MODE_LABELS: Record<ReplyMode, string> = {
  auto: "AUTO",
  voice: "VOZ",
  text: "TXT",
  both: "V+T",
};

interface Props {
  value: ReplyMode;
  onChanged: (mode: ReplyMode) => void;
  fetchImpl?: typeof fetch;
}

export function ModeReadout({ value, onChanged, fetchImpl }: Props) {
  const [active, setActive] = useState<ReplyMode>(value);

  useEffect(() => {
    setActive(value);
  }, [value]);

  const choose = async (mode: ReplyMode) => {
    const previous = active;
    setActive(mode);
    try {
      const settings = await createApi(fetchImpl).patchSettings(mode);
      setActive(settings.reply_mode);
      onChanged(settings.reply_mode);
    } catch {
      setActive(previous);
    }
  };

  return (
    <div role="radiogroup" aria-label="Modo de respuesta" className="hud-modes">
      {REPLY_MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          role="radio"
          aria-label={MODE_LABELS[mode]}
          aria-checked={active === mode}
          className={active === mode ? "hud-chip active" : "hud-chip"}
          onClick={() => void choose(mode)}
        >
          {MODE_LABELS[mode]}
        </button>
      ))}
    </div>
  );
}
