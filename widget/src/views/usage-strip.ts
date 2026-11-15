// Claude usage at the top of the panel (every tab and the session detail), so the
// Session / Weekly limits, the live rate, subagents and today's cost stay visible once
// the OSD is expanded. Same data as the OSD (`osd` SSE), refreshed in place by main.ts.
import { h } from "../dom";
import { cost, limitLevel, pct, rate, resetIn } from "../osd-format";
import type { Limit, Osd, Skin } from "../types";

export const STRIP_CLASS = "ustrip";
const ASCII_CELLS = 12;

function meter(limit: Limit, skin: Skin): HTMLElement {
  if (skin === "terminal") {
    const full = Math.round((limit.used_pct / 100) * ASCII_CELLS);
    return h(
      "span",
      { class: "ustrip__ascii", "aria-hidden": "true" },
      h("span", { class: "ustrip__ascii-fill" }, "█".repeat(full)),
      "░".repeat(ASCII_CELLS - full),
    );
  }
  const fill = h("span", { class: "ustrip__fill" });
  fill.style.width = `${limit.used_pct}%`; // CSSOM, allowed by the CSP
  return h("span", { class: "ustrip__track", "aria-hidden": "true" }, fill);
}

function limitRow(limit: Limit, skin: Skin): HTMLElement {
  const reset = resetIn(limit.resets_at);
  return h(
    "div",
    {
      class: `ustrip__row ustrip__row--${limitLevel(limit.used_pct)}`,
      role: "meter",
      "aria-valuemin": 0,
      "aria-valuemax": 100,
      "aria-valuenow": Math.round(limit.used_pct),
      "aria-label": `${limit.label} ${pct(limit.used_pct)}${reset ? `, réinitialisé dans ${reset}` : ""}`,
    },
    h("span", { class: "ustrip__label" }, limit.label),
    meter(limit, skin),
    h("span", { class: "ustrip__pct" }, pct(limit.used_pct)),
    h("span", { class: "ustrip__reset" }, reset),
  );
}

function metaLine(osd: Osd): HTMLElement {
  const live = osd.live.is_live;
  return h(
    "div",
    { class: "ustrip__meta" },
    h(
      "span",
      { class: live ? "ustrip__live" : "ustrip__idle" },
      live ? `● ${rate(osd.live.tokens_per_minute)} tok/min` : "○ repos",
    ),
    osd.subagents > 0 ? h("span", {}, `⚙ ${osd.subagents} sous-agent${osd.subagents > 1 ? "s" : ""}`) : null,
    osd.today_cost_usd !== null ? h("span", { title: "Tours vus depuis le démarrage du démon" }, `aujourd'hui ${cost(osd.today_cost_usd)}`) : null,
  );
}

export function usageStrip(osd: Osd | null, skin: Skin): HTMLElement {
  const limits = osd?.limits.slice(0, 3) ?? [];
  return h(
    "section",
    { class: STRIP_CLASS, "aria-label": "Utilisation Claude" },
    limits.length > 0
      ? h("div", { class: "ustrip__rows" }, ...limits.map((l) => limitRow(l, skin)))
      : h("p", { class: "ustrip__hint" }, "Limites inconnues : activez la statusline (omniscient group setup)."),
    osd ? metaLine(osd) : null,
  );
}

/** Puts the strip right under the panel's tab bar (or its header in the detail view). */
export function withUsageStrip(panel: HTMLElement, strip: HTMLElement): HTMLElement {
  const anchor = panel.querySelector(":scope > .tabs") ?? panel.querySelector(":scope > header");
  if (anchor) anchor.after(strip);
  else panel.prepend(strip);
  return panel;
}
