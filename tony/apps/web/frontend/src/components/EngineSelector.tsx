import { useEffect, useState } from "react";

import type { Api, EnginesView } from "../api/client";

interface Props {
  api: Api;
  busy: boolean;
}

export function EngineSelector({ api, busy }: Props) {
  const [view, setView] = useState<EnginesView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getEngines().then(setView).catch((err: Error) => setError(err.message));
  }, [api]);

  if (view === null) {
    return null;
  }

  const onChange = (profile: string) => {
    setError(null);
    api
      .patchEngine(profile)
      .then(setView)
      .catch((err: Error) => setError(err.message));
  };

  return (
    <div className="hud-corner holo">
      <select
        aria-label="Motor"
        value={view.active}
        disabled={busy}
        onChange={(event) => onChange(event.target.value)}
      >
        {view.profiles.map((profile) => (
          <option key={profile.name} value={profile.name}>
            {profile.name}
          </option>
        ))}
      </select>
      {error ? <p className="warn">{error}</p> : null}
    </div>
  );
}
