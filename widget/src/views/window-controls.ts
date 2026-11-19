// Window controls at the top-right of every layout: « − » minimizes to the taskbar,
// « + » switches between the small (OSD) and the large (panel) layout, « ✕ » quits the app. Icons are SVG built
// with DOM APIs (strict CSP); in the terminal skin they turn into plain characters (CSS).
import { closeApp, minimizeWindow } from "../api";
import { h, svg } from "../dom";

export type Layout = "small" | "large";

export interface WindowControlHandlers {
  /** Switch layout: enlarge when `small`, fold to the OSD when `large`. */
  toggle(): void;
}

const ICON_SIZE = 16;

function icon(paths: readonly string[], glyph: string): HTMLElement {
  const root = svg("svg", {
    viewBox: "0 0 16 16",
    width: ICON_SIZE,
    height: ICON_SIZE,
    class: "wc__svg",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": 1.6,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true",
    focusable: "false",
  });
  for (const d of paths) root.append(svg("path", { d }));
  return h("span", { class: "wc__icon", "aria-hidden": "true" }, root, h("span", { class: "wc__glyph" }, glyph));
}

const MINUS = icon(["M3.5 8h9"], "−");
const CLOSE = icon(["M4 4l8 8", "M12 4l-8 8"], "×");
const PLUS = icon(["M8 3.5v9", "M3.5 8h9"], "+");
// Two arrows pointing inward: fold back to the compact view.
const COMPACT = icon(["M13 3 9.5 6.5", "M9.5 3.5v3h3", "M3 13l3.5-3.5", "M3.5 9.5h3v3"], "+");

function button(label: string, icon: HTMLElement, action: () => void, extra = ""): HTMLButtonElement {
  // Stop the click and the keyboard activation here: the OSD (role=button) opens the panel
  // on click / Enter / Space and the panel header folds on click.
  const stop = (event: Event): void => event.stopPropagation();
  return h(
    "button",
    {
      class: `icon-btn wc__btn ${extra}`.trim(),
      type: "button",
      "aria-label": label,
      title: label,
      onclick: ((event: Event) => {
        stop(event);
        action();
      }) as EventListener,
      onkeydown: stop as EventListener,
    },
    icon,
  );
}

export function windowControls(layout: Layout, on: WindowControlHandlers): HTMLElement {
  const minimize = (): void => {
    minimizeWindow().catch((err: unknown) => console.warn("omniscient: minimize failed", err));
  };
  const close = (): void => {
    closeApp().catch((err: unknown) => console.warn("omniscient: quit failed", err));
  };
  const toggleLabel = layout === "small" ? "Agrandir" : "Passer en vue compacte";
  return h(
    "span",
    { class: `wc wc--${layout}`, role: "group", "aria-label": "Fenêtre" },
    button("Réduire dans la barre des tâches", MINUS.cloneNode(true) as HTMLElement, minimize),
    button(toggleLabel, (layout === "small" ? PLUS : COMPACT).cloneNode(true) as HTMLElement, on.toggle),
    button("Fermer Omniscient", CLOSE.cloneNode(true) as HTMLElement, close, "wc__btn--close"),
  );
}
