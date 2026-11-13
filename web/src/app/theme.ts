export type Theme = "light" | "dark" | "black";

export const THEME_STORAGE_KEY = "relay-theme-v1";
export const THEMES: readonly Theme[] = ["light", "dark", "black"];

function isTheme(value: string | null): value is Theme {
  return value !== null && THEMES.includes(value as Theme);
}

export function readInitialTheme(storage: Storage, _prefersDark: boolean): Theme {
  const saved = storage.getItem(THEME_STORAGE_KEY);
  if (isTheme(saved)) return saved;
  return "black";
}

export function applyTheme(
  theme: Theme,
  storage: Storage,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset.theme = theme;
  storage.setItem(THEME_STORAGE_KEY, theme);
}
