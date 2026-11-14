// The menu's DOM: a header with the eye, « Vue OSD » as a segmented switch, « Thème » as
// radio rows with a swatch of each skin, the ticker toggle, then corner / quit.
import { h } from "../dom";
import { eyeMark } from "../eye";
import { CORNER_ID, type MenuSnapshot, QUIT_ID, THEMES, TICKER_ID, VIEWS, themeId, viewId } from "./model";

const LOCK_HINT = "Fixé dans ~/.claude/settings.json";

function section(title: string, locked: boolean, ...items: HTMLElement[]): HTMLElement {
  return h(
    "div",
    { class: "menu__section", role: "group", "aria-label": title },
    h("div", { class: "menu__label" }, title, locked && h("span", { class: "menu__lock", title: LOCK_HINT }, "settings.json")),
    ...items,
  );
}

function viewSwitch(snap: MenuSnapshot): HTMLElement {
  const buttons = VIEWS.map((v) =>
    h(
      "button",
      {
        class: "menu__seg",
        role: "menuitemradio",
        "aria-checked": String(snap.osd_view === v.id),
        "data-id": viewId(v.id),
        disabled: snap.view_locked,
        type: "button",
      },
      v.label,
    ),
  );
  return h("div", { class: "menu__segs" }, ...buttons);
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

function tickerRow(snap: MenuSnapshot): HTMLElement {
  return h(
    "button",
    {
      class: "menu__item",
      role: "menuitemcheckbox",
      "aria-checked": String(snap.show_ticker),
      "data-id": TICKER_ID,
      disabled: snap.ticker_locked,
      title: snap.ticker_locked ? LOCK_HINT : undefined,
      type: "button",
    },
    h("span", { class: "menu__icon", "aria-hidden": "true" }, "≋"),
    h("span", { class: "menu__text" }, "Afficher le ticker"),
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
    h("div", { class: "menu__sep", role: "separator" }),
    tickerRow(snap),
    h("div", { class: "menu__sep", role: "separator" }),
    action(CORNER_ID, "⌖", "Replacer dans le coin"),
    action(QUIT_ID, "⏻", "Quitter", true),
  );
}
