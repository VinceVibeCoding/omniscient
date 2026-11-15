// « Fournisseurs IA »: Claude Code is the default; a person who only has a Gemini, OpenAI
// or Anthropic key (or a local model) can add it here and chat with it. The key field is a
// password input that is emptied once sent; the list only ever shows « clé …1234 ».
import { h } from "../dom";
import type { NewProvider, ProviderHandlers, ProviderModel } from "../provider-controller";
import type { Provider } from "../types";

const KIND_CHOICES: readonly { id: NewProvider["kind"]; label: string; hint: string }[] = [
  { id: "gemini", label: "Google Gemini", hint: "Clé API Google AI Studio" },
  { id: "openai", label: "OpenAI", hint: "Clé API OpenAI" },
  { id: "anthropic", label: "Anthropic (API)", hint: "Clé API Anthropic" },
  { id: "openai-compatible", label: "Serveur compatible OpenAI", hint: "Ollama, LM Studio, OpenRouter, Groq…" },
];
const MODELS_SHOWN = 80;

function status(p: Provider, isDefault: boolean): HTMLElement {
  const bits: string[] = [];
  if (isDefault) bits.push("par défaut");
  if (p.builtin) bits.push("utilise votre connexion Claude");
  else bits.push(p.has_key ? `clé …${p.key_hint}` : "sans clé");
  if (!p.builtin && p.model === "") bits.push("modèle à choisir");
  return h("span", { class: "prov__status" }, bits.join(" · "));
}

function modelPicker(p: Provider, models: readonly string[], on: ProviderHandlers): HTMLElement | null {
  if (p.builtin) return null;
  if (models.length === 0) {
    return p.model ? h("span", { class: "prov__model" }, p.model) : null;
  }
  const select = h("select", { class: "prov__select", "aria-label": `Modèle de ${p.label}` });
  if (!models.includes(p.model)) select.append(h("option", { value: "" }, "Choisir un modèle…"));
  for (const m of models.slice(0, MODELS_SHOWN)) {
    const option = h("option", { value: m }, m);
    option.selected = m === p.model;
    select.append(option);
  }
  select.addEventListener("change", () => select.value && on.chooseModel(p.id, select.value));
  return select;
}

function row(p: Provider, m: ProviderModel, on: ProviderHandlers): HTMLElement {
  const isDefault = m.list.default === p.id;
  return h(
    "li",
    { class: "prov__row" },
    h("div", { class: "prov__main" }, h("span", { class: "prov__name" }, p.label), status(p, isDefault)),
    modelPicker(p, m.models[p.id] ?? [], on),
    h(
      "div",
      { class: "card__actions" },
      h("button", { class: "btn", type: "button", disabled: m.busy, onclick: () => on.test(p.id) }, "Tester"),
      isDefault ? null : h("button", { class: "btn btn--ghost", type: "button", onclick: () => on.makeDefault(p.id) }, "Par défaut"),
      p.builtin ? null : h("button", { class: "btn btn--ghost", type: "button", onclick: () => on.remove(p.id) }, "Retirer"),
    ),
  );
}

function addForm(m: ProviderModel, on: ProviderHandlers): HTMLElement {
  const local = m.draft.kind === "openai-compatible";
  const kind = h("select", { name: "kind", "aria-label": "Fournisseur" });
  for (const k of KIND_CHOICES) {
    const option = h("option", { value: k.id }, k.label);
    option.selected = k.id === m.draft.kind;
    kind.append(option);
  }
  const hint = h("span", { class: "setting__hint" }, KIND_CHOICES.find((k) => k.id === m.draft.kind)?.hint ?? "");
  const url = h("input", { name: "base_url", value: m.draft.base_url, placeholder: "http://127.0.0.1:11434/v1", spellcheck: "false", autocomplete: "off" });
  url.addEventListener("input", () => on.setDraft({ base_url: url.value }));
  const urlField = h("label", { class: "setting", hidden: !local }, h("span", { class: "setting__label" }, "Adresse du serveur"), url);
  const key = h("input", {
    name: "api_key",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "Collez la clé ici",
    "aria-label": "Clé API",
  });
  const keyLabel = h("span", { class: "setting__label" }, local ? "Clé API (facultative en local)" : "Clé API");
  const label = h("input", { name: "label", value: m.draft.label, placeholder: "Nom (facultatif)", maxlength: 60, autocomplete: "off" });
  label.addEventListener("input", () => on.setDraft({ label: label.value }));
  kind.addEventListener("change", () => {
    const isLocal = kind.value === "openai-compatible";
    urlField.hidden = !isLocal;
    keyLabel.textContent = isLocal ? "Clé API (facultative en local)" : "Clé API";
    hint.textContent = KIND_CHOICES.find((k) => k.id === kind.value)?.hint ?? "";
    on.setDraft({ kind: kind.value as NewProvider["kind"] });
  });
  const form = h(
    "form",
    { class: "settings prov__add" },
    h("h3", { class: "section-title" }, "Ajouter un fournisseur"),
    h("label", { class: "setting" }, h("span", { class: "setting__label" }, "Fournisseur"), kind, hint),
    urlField,
    h("label", { class: "setting" }, keyLabel, key, h("span", { class: "setting__hint" }, "Gardée sur cet ordinateur, jamais affichée de nouveau.")),
    h("label", { class: "setting" }, h("span", { class: "setting__label" }, "Nom"), label),
    h("div", { class: "card__actions" }, h("button", { class: "btn btn--primary", type: "submit", disabled: m.busy }, "Ajouter et tester")),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const chosen = kind.value as NewProvider["kind"];
    on.add({ kind: chosen, label: label.value.trim(), base_url: url.value.trim(), api_key: key.value.trim() });
    key.value = ""; // the key leaves the page as soon as it is sent
    key.blur(); // a focused field holds redraws back: let the result show
  });
  return form;
}

export function providersSection(m: ProviderModel, on: ProviderHandlers): HTMLElement {
  return h(
    "section",
    { class: "prov", "aria-label": "Fournisseurs IA" },
    h("p", { class: "setting__hint" }, "Claude Code est utilisé par défaut. Ajoutez un autre fournisseur si vous n'avez que celui-là (Gemini, OpenAI…) : la conversation y est un simple échange, sans outils."),
    h("ul", { class: "prov__list" }, ...m.list.providers.map((p) => row(p, m, on))),
    m.notice ? h("p", { class: "notice", role: "status" }, m.notice) : null,
    addForm(m, on),
  );
}
