import { describe, expect, it } from "vitest";

import { applyTheme, readInitialTheme } from "./theme";

function storageWith(value: string | null): Storage {
  const values = new Map<string, string>();
  if (value !== null) values.set("relay-theme-v1", value);
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, next) => values.set(key, next),
  };
}

describe("theme preference", () => {
  it("keeps an explicit Black choice even when the system prefers light", () => {
    expect(readInitialTheme(storageWith("black"), false)).toBe("black");
  });

  it("starts fresh and invalid preferences in true Black", () => {
    expect(readInitialTheme(storageWith(null), true)).toBe("black");
    expect(readInitialTheme(storageWith(null), false)).toBe("black");
    expect(readInitialTheme(storageWith("sepia"), false)).toBe("black");
  });

  it("applies and persists a selected theme", () => {
    const storage = storageWith(null);
    const root = document.createElement("html");
    applyTheme("black", storage, root);
    expect(root.dataset.theme).toBe("black");
    expect(storage.getItem("relay-theme-v1")).toBe("black");
  });
});
