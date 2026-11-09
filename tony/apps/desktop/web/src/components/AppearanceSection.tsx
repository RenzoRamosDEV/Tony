import { THEMES, type ThemeId } from "../theme/themes";

interface Props {
  theme: ThemeId;
  onChange: (theme: ThemeId) => void;
}

export function AppearanceSection({ theme, onChange }: Props) {
  return (
    <div role="radiogroup" aria-labelledby="appearance-title" className="appearance-section">
      <h3 id="appearance-title" className="holo">
        Apariencia
      </h3>
      <div className="theme-options">
        {THEMES.map((option) => (
          <label key={option.id} className="theme-option">
            <input
              type="radio"
              name="theme"
              value={option.id}
              checked={option.id === theme}
              onChange={() => onChange(option.id)}
            />
            <span className="theme-swatch" data-theme={option.id} aria-hidden="true" />
            <span className="theme-name">{option.name}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
