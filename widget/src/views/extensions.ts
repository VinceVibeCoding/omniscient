// Réglages › Extensions: what is installed, on/off, removal (with a confirmation step),
// load errors, themes and the hint to ask the AI for a new one. All text through h().
import type { Extension, ExtTheme } from "../api-ext";
import { h } from "../dom";
import type { ExtHandlers, ExtModel } from "../ext-controller";
import { safeThemeColors } from "../ext-logic";

const plural = (n: number, one: string, many: string): string => `${n} ${n > 1 ? many : one}`;

function counts(e: Extension): string {
  const bits = [
    plural(e.commands.length, "commande", "commandes"),
    plural(e.workflows.length, "workflow", "workflows"),
    plural(e.themes.length, "thème", "thèmes"),
    plural(e.presets.length, "préréglage", "préréglages"),
  ];
  return bits.join(" · ");
}

function themeRow(e: Extension, t: ExtTheme, m: ExtModel, on: ExtHandlers): HTMLElement {
  const active = m.theme?.extension === e.id && m.theme.theme === t.id;
  const usable = safeThemeColors(t.colors).length > 0;
  return h(
    "div",
    { class: "ext__theme" },
    h("span", { class: "ext__theme-name" }, active ? `${t.label} (appliqué)` : t.label),
    active
      ? h("button", { class: "btn btn--ghost", type: "button", onclick: on.resetTheme }, "Revenir au thème d'origine")
      : h("button", { class: "btn", type: "button", disabled: !usable || !e.enabled, onclick: () => on.applyTheme({ extension: e.id, theme: t.id }) }, "Appliquer"),
  );
}

function removeRow(e: Extension, m: ExtModel, on: ExtHandlers): HTMLElement {
  if (m.confirming !== e.id) {
    return h("button", { class: "btn btn--ghost", type: "button", disabled: m.busy, onclick: () => on.askRemove(e.id) }, "Retirer");
  }
  return h(
    "span",
    { class: "ext__confirm", role: "group", "aria-label": `Retirer ${e.name}` },
    h("span", { class: "setting__hint" }, "Supprimer son dossier ?"),
    h("button", { class: "btn btn--danger", type: "button", disabled: m.busy, onclick: () => on.remove(e.id) }, "Oui, retirer"),
    h("button", { class: "btn btn--ghost", type: "button", onclick: () => on.askRemove(null) }, "Annuler"),
  );
}

function extensionRow(e: Extension, m: ExtModel, on: ExtHandlers): HTMLElement {
  const box = h("input", { type: "checkbox", checked: e.enabled, disabled: m.busy, "aria-label": `Activer ${e.name}` });
  box.addEventListener("change", () => on.setEnabled(e.id, box.checked));
  const meta = [e.version ? `v${e.version}` : "", e.author].filter(Boolean).join(" · ");
  return h(
    "li",
    { class: "ext__row" },
    h("label", { class: "setting setting--check" }, box, h("span", { class: "setting__label" }, `${e.name}${meta ? ` · ${meta}` : ""}`)),
    e.description ? h("p", { class: "setting__hint" }, e.description) : null,
    h("p", { class: "setting__hint" }, e.enabled ? counts(e) : `Désactivée · ${counts(e)}`),
    ...e.themes.map((t) => themeRow(e, t, m, on)),
    h("div", { class: "card__actions" }, removeRow(e, m, on)),
  );
}

export function extensionsSection(m: ExtModel, on: ExtHandlers): HTMLElement {
  const { extensions, errors } = m.view;
  return h(
    "section",
    { class: "ext", "aria-label": "Extensions" },
    h(
      "p",
      { class: "setting__hint" },
      "Une extension est un dossier de données (jamais du code) : commandes, thèmes, workflows, préréglages. Demandez-le à Claude dans un chat sur votre dossier Omniscient, puis tapez /reload.",
    ),
    extensions.length === 0 ? h("p", { class: "empty" }, "Aucune extension installée.") : h("ul", { class: "ext__list" }, ...extensions.map((e) => extensionRow(e, m, on))),
    ...errors.map((err) => h("p", { class: "notice notice--error", role: "alert" }, `${err.id ? `${err.id} : ` : ""}${err.message}`)),
    h("div", { class: "card__actions" }, h("button", { class: "btn", type: "button", disabled: m.busy, onclick: on.reload }, "Recharger")),
  );
}
