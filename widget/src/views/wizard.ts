// First-run assistant: 1. connect the widget to the daemon, 2. choose the AI provider
// (Claude Code by default, others optional), 3. pick a look. Each step can be skipped; the
// whole assistant can be left at any time (« Passer »).
import { h } from "../dom";
import { eyeMark } from "../eye";
import type { AccountHandlers, AccountModel } from "../account-controller";
import type { ProviderHandlers, ProviderModel } from "../provider-controller";
import type { LinkStatus, Skin } from "../types";
import { accountSection } from "./account";
import { providersSection } from "./providers";
import { emailForm, pairingForm, type SettingsHandlers } from "./settings";

export const WIZARD_STEPS = ["Connexion", "Compte", "Fournisseur IA", "Apparence"] as const;

export interface WizardModel {
  step: number;
  link: LinkStatus;
  providers: ProviderModel;
  account: AccountModel;
  skin: Skin;
}

export interface WizardHandlers {
  go(step: number): void;
  finish(): void;
  pair: Pick<SettingsHandlers, "pairStart" | "pairFinish" | "emailStart" | "emailVerify" | "unpair">;
  providers: ProviderHandlers;
  account: AccountHandlers;
  setSkin(skin: Skin): void;
}

const SKINS: readonly { id: Skin; label: string; hint: string }[] = [
  { id: "default", label: "Default", hint: "Palette Omniscient" },
  { id: "terminal", label: "Terminal", hint: "Vert sur noir" },
  { id: "dashboard", label: "Dashboard", hint: "Bleu Bloomberg" },
];

function stepConnect(m: WizardModel, on: WizardHandlers): HTMLElement {
  if (m.link.state === "connected") {
    return h("p", { class: "notice notice--connected", role: "status" }, "Connecté au démon. ✓");
  }
  return h(
    "div",
    {},
    h("p", { class: `notice notice--${m.link.state}`, role: "status" }, m.link.message),
    emailForm(on.pair),
    pairingForm({ ...on.pair, back: () => undefined, collapse: () => undefined, save: () => undefined, autostart: () => undefined, wizard: () => undefined }),
  );
}

function stepSkin(m: WizardModel, on: WizardHandlers): HTMLElement {
  return h(
    "div",
    { class: "wizard__skins", role: "radiogroup", "aria-label": "Apparence" },
    ...SKINS.map((s) =>
      h(
        "button",
        {
          class: `btn wizard__skin ${m.skin === s.id ? "btn--primary" : ""}`,
          type: "button",
          role: "radio",
          "aria-checked": String(m.skin === s.id),
          onclick: () => on.setSkin(s.id),
        },
        h("strong", {}, s.label),
        h("small", {}, s.hint),
      ),
    ),
  );
}

export function wizardView(m: WizardModel, on: WizardHandlers): HTMLElement {
  const last = m.step === WIZARD_STEPS.length - 1;
  const body =
    m.step === 0
      ? stepConnect(m, on)
      : m.step === 1
        ? accountSection(m.account, on.account)
        : m.step === 2
          ? providersSection(m.providers, on.providers)
          : stepSkin(m, on);
  return h(
    "section",
    { class: "panel panel--wizard", "aria-label": "Bienvenue" },
    h(
      "header",
      { class: "bar" },
      eyeMark(20, m.link.state === "connected"),
      h("h1", { class: "bar__title" }, "Bienvenue"),
      h("button", { class: "btn btn--ghost", type: "button", onclick: on.finish }, "Passer"),
    ),
    h(
      "ol",
      { class: "wizard__steps", "aria-label": "Étapes" },
      ...WIZARD_STEPS.map((name, i) =>
        h("li", { class: i === m.step ? "wizard__step wizard__step--on" : "wizard__step", "aria-current": i === m.step ? "step" : undefined }, `${i + 1}. ${name}`),
      ),
    ),
    h("div", { class: "panel__body" }, body),
    h(
      "footer",
      { class: "wizard__nav card__actions" },
      m.step > 0 ? h("button", { class: "btn btn--ghost", type: "button", onclick: () => on.go(m.step - 1) }, "Précédent") : null,
      h("button", { class: "btn btn--primary", type: "button", onclick: () => (last ? on.finish() : on.go(m.step + 1)) }, last ? "Terminer" : "Suivant"),
    ),
  );
}
