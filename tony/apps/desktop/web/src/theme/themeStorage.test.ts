import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, loadTheme, saveTheme, type KeyValueStore } from "./themeStorage";

class FakeStore implements KeyValueStore {
  values = new Map<string, string>();
  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStore implements KeyValueStore {
  getItem(): string | null {
    throw new Error("storage blocked");
  }
  setItem(): void {
    throw new Error("quota exceeded");
  }
}

describe("loadTheme", () => {
  it("returns holo when nothing was saved", () => {
    expect(loadTheme(new FakeStore())).toBe("holo");
  });

  it("restores a saved theme", () => {
    const store = new FakeStore();
    store.setItem(THEME_STORAGE_KEY, "instrumento");
    expect(loadTheme(store)).toBe("instrumento");
  });

  it("falls back to holo for a corrupt value", () => {
    const store = new FakeStore();
    store.setItem(THEME_STORAGE_KEY, "{corrupt");
    expect(loadTheme(store)).toBe("holo");
  });

  it("falls back to holo when storage throws", () => {
    expect(loadTheme(new ThrowingStore())).toBe("holo");
  });

  it("falls back to holo when there is no storage", () => {
    expect(loadTheme(null)).toBe("holo");
  });
});

describe("saveTheme", () => {
  it("writes the theme id under the storage key", () => {
    const store = new FakeStore();
    saveTheme("aurora", store);
    expect(store.values.get(THEME_STORAGE_KEY)).toBe("aurora");
  });

  it("does not throw when storage throws or is missing", () => {
    expect(() => saveTheme("aurora", new ThrowingStore())).not.toThrow();
    expect(() => saveTheme("aurora", null)).not.toThrow();
  });
});
