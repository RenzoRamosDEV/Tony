export type ThemeId = "holo" | "aurora" | "instrumento";

export interface ThemeOption {
  id: ThemeId;
  name: string;
}

export const THEMES: readonly ThemeOption[] = [
  { id: "holo", name: "Holo Ámbar" },
  { id: "aurora", name: "Aurora" },
  { id: "instrumento", name: "Instrumento" },
];

export const DEFAULT_THEME: ThemeId = "holo";

export function parseThemeId(raw: unknown): ThemeId {
  return THEMES.find((theme) => theme.id === raw)?.id ?? DEFAULT_THEME;
}
