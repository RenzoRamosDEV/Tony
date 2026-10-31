import { useEffect, useState } from "react";

import type { Api, EnginesView } from "../api/client";

interface Props {
  api: Api;
  busy: boolean;
}

const MISSING_API_KEY_MESSAGE = "Configura una API key antes de seleccionar este motor.";

export function EngineSelector({ api, busy }: Props) {
  const [view, setView] = useState<EnginesView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [credentialProfile, setCredentialProfile] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    api.getEngines().then(setView).catch((err: Error) => setError(err.message));
  }, [api]);

  if (view === null) {
    return null;
  }

  const openCredentialForm = (profile: EnginesView["profiles"][number]) => {
    setCredentialProfile(profile.name);
    setModel(profile.model ?? "");
    setApiKey("");
  };

  const closeCredentialForm = () => {
    setCredentialProfile(null);
    setModel("");
    setApiKey("");
  };

  const onChange = (profileName: string) => {
    setError(null);
    const profile = view.profiles.find((candidate) => candidate.name === profileName);
    if (profile?.auth === "api_key" && !profile.configured) {
      openCredentialForm(profile);
      return;
    }
    api
      .patchEngine(profileName)
      .then(setView)
      .catch((err: Error) => {
        if (err.message === MISSING_API_KEY_MESSAGE && profile) {
          openCredentialForm(profile);
          return;
        }
        setError(err.message);
      });
  };

  const onSaveCredentials = () => {
    if (credentialProfile === null) {
      return;
    }
    setError(null);
    api
      .configureEngine(credentialProfile, model, apiKey)
      .then((updated) => {
        setView(updated);
        closeCredentialForm();
      })
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
      {credentialProfile !== null ? (
        <div className="credential-form">
          <label htmlFor="engine-credential-model">Modelo</label>
          <input
            id="engine-credential-model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
          />
          <label htmlFor="engine-credential-api-key">API key</label>
          <input
            id="engine-credential-api-key"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
          <button type="button" onClick={onSaveCredentials}>
            Guardar
          </button>
          <button type="button" onClick={closeCredentialForm}>
            Cancelar
          </button>
        </div>
      ) : null}
      {error ? <p className="warn">{error}</p> : null}
    </div>
  );
}
