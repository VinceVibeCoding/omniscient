// Themes from extensions: custom colours set on top of the built-in skins. Only allowlisted
// CSS variables are touched, through CSSOM (`style.setProperty`, allowed by the strict CSP),
// and clearing removes exactly the properties this module set. The choice (extension id +
// theme id) is remembered in localStorage, which may throw or be empty: never relied upon.
import type { ExtensionsView, ExtTheme } from "./api-ext";
import { safeThemeColors } from "./ext-logic";

const STORAGE_KEY = "omniscient.ext-theme";
const ID = /^[a-z0-9][a-z0-9-]{0,39}$/;

export interface ThemeChoice {
  extension: string;
  theme: string;
}

/** What this module set on the root (property and value), in order. */
let painted: [string, string][] = [];
let current: ThemeChoice | null = null;

function root(): HTMLElement {
  return document.documentElement;
}

/** Removes exactly the properties set by the last `paintTheme`. */
export function clearPainted(): void {
  for (const [prop] of painted) root().style.removeProperty(prop);
  painted = [];
}

/** Sets the validated colours of `theme`; returns how many were applied. */
function paintTheme(theme: ExtTheme): number {
  clearPainted();
  for (const [prop, value] of safeThemeColors(theme.colors)) {
    root().style.setProperty(prop, value);
    painted.push([prop, value]);
  }
  return painted.length;
}

function remember(choice: ThemeChoice | null): void {
  try {
    if (choice) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(choice));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage blocked: the theme just won't survive a restart
  }
}

function recall(): ThemeChoice | null {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
    if (typeof parsed !== "object" || parsed === null) return null;
    const { extension, theme } = parsed as Record<string, unknown>;
    if (typeof extension !== "string" || typeof theme !== "string" || !ID.test(extension) || !ID.test(theme)) return null;
    return { extension, theme };
  } catch {
    return null;
  }
}

export function currentChoice(): ThemeChoice | null {
  return current;
}

/** « Appliquer »: false when the theme has nothing valid to apply. */
export function applyChoice(view: ExtensionsView, choice: ThemeChoice): boolean {
  const theme = findTheme(view, choice);
  if (!theme || paintTheme(theme) === 0) return false;
  current = choice;
  remember(choice);
  return true;
}

/** « Revenir au thème d'origine ». */
export function resetTheme(): void {
  clearPainted();
  current = null;
  remember(null);
}

function findTheme(view: ExtensionsView, choice: ThemeChoice): ExtTheme | undefined {
  const ext = view.extensions.find((e) => e.id === choice.extension && e.enabled);
  return ext?.themes.find((t) => t.id === choice.theme);
}

/** Re-applies the remembered (or current) choice after the extensions list changed or a skin
 * repainted; clears it and forgets it when the extension is gone, disabled or invalid. */
export function syncTheme(view: ExtensionsView): void {
  const choice = current ?? recall();
  if (!choice) return;
  const theme = findTheme(view, choice);
  if (theme && paintTheme(theme) > 0) {
    current = choice;
    return;
  }
  resetTheme();
}

/** Called by the skin code right after it repainted the root: the custom colours go back on top. */
export function repaintAfterSkin(): void {
  for (const [prop, value] of painted) root().style.setProperty(prop, value);
}
