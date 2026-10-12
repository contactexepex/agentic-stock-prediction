// The cockpit's colour theme (UX4): "system" follows the reader's device (prefers-color-scheme, the dark tokens'
// media query in styles/tokens-dark.css), "light" or "dark" sets data-theme on <html>. The choice is remembered per
// browser in localStorage; every read and write is wrapped, so a blocked storage only loses the memory. The boot
// script runs in <head> before the first paint, so a saved choice never flashes the other theme.

export const THEME_KEY = "mb-theme";
export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];
/** The event the toggle fires on window after a change, so charts drawn from the tokens redraw. */
export const THEME_EVENT = "mb-theme-change";

export const THEME_LABEL: Record<Theme, string> = { system: "System", light: "Light", dark: "Dark" };
export const THEME_ICON: Record<Theme, string> = { system: "contrast", light: "light_mode", dark: "dark_mode" };

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

/** The next choice of the toggle: System, then Light, then Dark, then System again. */
export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

/** The data-theme attribute a choice sets on <html>; null removes it (System: the media query decides). */
export function themeAttribute(theme: Theme): "light" | "dark" | null {
  return theme === "system" ? null : theme;
}

export function readTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    return isTheme(saved) ? saved : "system";
  } catch {
    return "system";
  }
}

export function saveTheme(theme: Theme): void {
  try {
    if (theme === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage blocked: the choice holds for this page only */
  }
}

export function applyTheme(theme: Theme): void {
  const attr = themeAttribute(theme);
  if (attr) document.documentElement.setAttribute("data-theme", attr);
  else document.documentElement.removeAttribute("data-theme");
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** The theme the page shows now, after the media query: what charts read their colours for. */
export function shownTheme(): "light" | "dark" {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Inlined in <head> by the root layout (a constant, never data): sets data-theme from the saved choice. */
export const THEME_BOOT_SCRIPT =
  `(function(){try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});` +
  `if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;
