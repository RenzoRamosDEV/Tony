import { useEffect, useState } from "react";

import { type KeyValueStore, browserStore, loadTheme, saveTheme } from "./themeStorage";
import type { ThemeId } from "./themes";

export function useTheme(store: KeyValueStore | null = browserStore()): [ThemeId, (theme: ThemeId) => void] {
  const [theme, setTheme] = useState<ThemeId>(() => loadTheme(store));

  useEffect(() => {
    document.documentElement.dataset["theme"] = theme;
  }, [theme]);

  const choose = (next: ThemeId) => {
    saveTheme(next, store);
    setTheme(next);
  };
  return [theme, choose];
}
