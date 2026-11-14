// What the right-click menu shows, from the snapshot Rust sends with `menu://open`
// (untrusted JSON: normalised here). Ids match src-tauri/src/osd_config.rs.
import type { OsdView, Skin } from "../types";

export interface MenuSnapshot {
  readonly theme: Skin;
  readonly osd_view: OsdView;
  readonly show_ticker: boolean;
  readonly theme_locked: boolean;
  readonly view_locked: boolean;
  readonly ticker_locked: boolean;
}

export const DEFAULT_SNAPSHOT: MenuSnapshot = {
  theme: "default",
  osd_view: "bars",
  show_ticker: true,
  theme_locked: false,
  view_locked: false,
  ticker_locked: false,
};

export const VIEWS: readonly { id: OsdView; label: string }[] = [
  { id: "bars", label: "Bars" },
  { id: "gauge", label: "Gauge" },
];

export const THEMES: readonly { id: Skin; label: string; hint: string }[] = [
  { id: "default", label: "Default", hint: "omniscient" },
  { id: "terminal", label: "Terminal", hint: "vert sur noir" },
  { id: "dashboard", label: "Dashboard", hint: "bloomberg" },
];

export const TICKER_ID = "ctx:ticker";
export const CORNER_ID = "ctx:corner";
export const QUIT_ID = "ctx:quit";
export const viewId = (view: OsdView): string => `ctx:view:${view}`;
export const themeId = (theme: Skin): string => `ctx:theme:${theme}`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function toSnapshot(raw: unknown): MenuSnapshot {
  if (!isRecord(raw)) return DEFAULT_SNAPSHOT;
  return {
    theme: THEMES.find((t) => t.id === raw.theme)?.id ?? DEFAULT_SNAPSHOT.theme,
    osd_view: VIEWS.find((v) => v.id === raw.osd_view)?.id ?? DEFAULT_SNAPSHOT.osd_view,
    show_ticker: bool(raw.show_ticker, true),
    theme_locked: bool(raw.theme_locked, false),
    view_locked: bool(raw.view_locked, false),
    ticker_locked: bool(raw.ticker_locked, false),
  };
}
