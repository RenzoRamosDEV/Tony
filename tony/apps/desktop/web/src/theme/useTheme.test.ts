import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, type KeyValueStore } from "./themeStorage";
import { useTheme } from "./useTheme";

class FakeStore implements KeyValueStore {
  values = new Map<string, string>();
  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

afterEach(() => document.documentElement.removeAttribute("data-theme"));

describe("useTheme", () => {
  it("starts on holo and marks the document", () => {
    const { result } = renderHook(() => useTheme(new FakeStore()));

    expect(result.current[0]).toBe("holo");
    expect(document.documentElement.dataset["theme"]).toBe("holo");
  });

  it("restores the saved theme on mount", () => {
    const store = new FakeStore();
    store.setItem(THEME_STORAGE_KEY, "aurora");

    const { result } = renderHook(() => useTheme(store));

    expect(result.current[0]).toBe("aurora");
    expect(document.documentElement.dataset["theme"]).toBe("aurora");
  });

  it("applies and persists a new choice immediately", () => {
    const store = new FakeStore();
    const { result } = renderHook(() => useTheme(store));

    act(() => result.current[1]("instrumento"));

    expect(result.current[0]).toBe("instrumento");
    expect(document.documentElement.dataset["theme"]).toBe("instrumento");
    expect(store.values.get(THEME_STORAGE_KEY)).toBe("instrumento");
  });

  it("keeps working when storage is unavailable", () => {
    const { result } = renderHook(() => useTheme(null));

    act(() => result.current[1]("aurora"));

    expect(document.documentElement.dataset["theme"]).toBe("aurora");
  });
});
