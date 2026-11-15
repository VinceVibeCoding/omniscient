// The menu's DOM: a header with the eye, « Vue OSD » as a segmented switch, « Thème » as
// radio rows with a swatch of each skin, the ticker toggle, then corner / quit.
import { h } from "../dom";
import { eyeMark } from "../eye";
import {
  AUTOSTART_ID,
  CORNER_ID,
  type MenuSnapshot,
  QUIT_ID,
  SCALES,
  THEMES,
  TICKER_ID,
  VIEWS,
  scaleId,
  themeId,
  viewId,
} from "./model";

const LOCK_HINT = "Fixé dans ~/.claude/settings.json";

function section(title: string, locked: boolean, ...items: HTMLElement[]): HTMLElement {
  return h(
    "div",
    { class: "menu__section", role: "group", "aria-label": title },
    h("div", { class: "menu__label" }, title, locked && h("span", { class: "menu__lock", title: LOCK_HINT }, "settings.json")),
    ...items,
  );
}

function segments(options: readonly { id: string; label: string; checked: boolean }[], locked: boolean): HTMLElement {
  const buttons = options.map((o) =>
    h(
      "button",
      { class: "menu__seg", role: "menuitemradio", "aria-checked": String(o.checked), "data-id": o.id, disabled: locked, type: "button" },
      o.label,
    ),
  );
  return h("div", { class: `menu__segs menu__segs--${options.length}` }, ...buttons);
}

function viewSwitch(snap: MenuSnapshot): HTMLElement {
  return segments(VIEWS.map((v) => ({ id: viewId(v.id), label: v.label, checked: snap.osd_view === v.id })), snap.view_locked);
}

function sizeSwitch(snap: MenuSnapshot): HTMLElement {
  // A size set with the grip may sit between presets: the nearest one is marked.
  const nearest = SCALES.reduce((a, b) => (Math.abs(b - snap.scale_pct) < Math.abs(a - snap.scale_pct) ? b : a));
  return segments(SCALES.map((pct) => ({ id: scaleId(pct), label: `${pct}%`, checked: pct === nearest })), false);
}

function themeRow(snap: MenuSnapshot, theme: (typeof THEMES)[number]): HTMLElement {
  const checked = snap.theme === theme.id;
  return h(
    "button",
    {
      class: "menu__item",
      role: "menuitemradio",
      "aria-checked": String(checked),
      "data-id": themeId(theme.id),
      disabled: snap.theme_locked,
      type: "button",
    },
    h("span", { class: `menu__swatch menu__swatch--${theme.id}`, "aria-hidden": "true" }),
    h("span", { class: "menu__text" }, theme.label, h("small", {}, theme.hint)),
    h("span", { class: "menu__check", "aria-hidden": "true" }, checked ? "●" : ""),
  );
}

function toggleRow(id: string, icon: string, label: string, on: boolean, locked = false): HTMLElement {
  return h(
    "button",
    {
      class: "menu__item",
      role: "menuitemcheckbox",
      "aria-checked": String(on),
      "data-id": id,
      disabled: locked,
      title: locked ? LOCK_HINT : undefined,
      type: "button",
    },
    h("span", { class: "menu__icon", "aria-hidden": "true" }, icon),
    h("span", { class: "menu__text" }, label),
    h("span", { class: "menu__toggle", "aria-hidden": "true" }, h("span", { class: "menu__knob" })),
  );
}

function action(id: string, icon: string, label: string, danger = false): HTMLElement {
  return h(
    "button",
    { class: danger ? "menu__item menu__item--danger" : "menu__item", role: "menuitem", "data-id": id, type: "button" },
    h("span", { class: "menu__icon", "aria-hidden": "true" }, icon),
    h("span", { class: "menu__text" }, label),
  );
}

export function menuView(snap: MenuSnapshot): HTMLElement {
  return h(
    "div",
    { class: "menu", role: "menu", "aria-label": "Omnigroup" },
    h("div", { class: "menu__head" }, eyeMark(18), h("span", { class: "menu__title" }, "Omnigroup")),
    section("OSD View", snap.view_locked, viewSwitch(snap)),
    section("Thème", snap.theme_locked, ...THEMES.map((t) => themeRow(snap, t))),
    section("Taille", false, sizeSwitch(snap)),
    h("div", { class: "menu__sep", role: "separator" }),
    toggleRow(TICKER_ID, "≋", "Afficher le ticker", snap.show_ticker, snap.ticker_locked),
    toggleRow(AUTOSTART_ID, "↻", "Lancer au démarrage", snap.autostart),
    h("div", { class: "menu__sep", role: "separator" }),
    action(CORNER_ID, "⌖", "Replacer dans le coin"),
    action(QUIT_ID, "⏻", "Quitter", true),
  );
}
