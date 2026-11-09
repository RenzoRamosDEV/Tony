import { type ThemeId, parseThemeId } from "./themes";

export const THEME_STORAGE_KEY = "tony.theme";

export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function browserStore(): KeyValueStore | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadTheme(store: KeyValueStore | null = browserStore()): ThemeId {
  try {
    return parseThemeId(store?.getItem(THEME_STORAGE_KEY));
  } catch {
    return parseThemeId(null);
  }
}

export function saveTheme(theme: ThemeId, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The choice still applies for this session when storage is unavailable.
  }
}
