// Settings / pairing panel. The widget token never reaches this page: pairing only
// sends the 6-digit code shown on the Windows desktop, Rust keeps the token.
import { h } from "../dom";
import type { LinkStatus, Settings } from "../types";
import { windowControls } from "./window-controls";

export interface SettingsHandlers {
  back(): void;
  /** Fold to the small OSD layout. */
  collapse(): void;
  save(settings: Settings): void;
  pairStart(): void;
  pairFinish(code: string): void;
  /** E-mail sign-in: ask for a code, then trade it (typed once, kept across sessions). */
  emailStart(email: string): void;
  emailVerify(email: string, code: string): void;
  unpair(): void;
  autostart(enabled: boolean): void;
  /** Open the first-run assistant again. */
  wizard(): void;
  /** Open the About screen (first screen built with React). */
  about(): void;
}

function checkbox(name: string, checked: boolean): HTMLInputElement {
  return h("input", { type: "checkbox", name, checked });
}

function startupSection(autostart: boolean | null, on: SettingsHandlers): HTMLElement {
  const box = checkbox("autostart", autostart === true);
  box.disabled = autostart === null;
  box.addEventListener("change", () => on.autostart(box.checked));
  return h(
    "label",
    { class: "setting setting--check" },
    box,
    h("span", { class: "setting__label" }, "Lancer Omniscient au démarrage de Windows"),
  );
}

function field(label: string, input: HTMLInputElement, hint?: string): HTMLElement {
  return h("label", { class: "setting" }, h("span", { class: "setting__label" }, label), input, hint ? h("span", { class: "setting__hint" }, hint) : null);
}

export function emailForm(on: Pick<SettingsHandlers, "emailStart" | "emailVerify">): HTMLElement {
  const email = h("input", { name: "email", type: "email", autocomplete: "email", spellcheck: "false", placeholder: "vous@exemple.com" });
  const code = h("input", { name: "email_code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 10, spellcheck: "false", placeholder: "123456" });
  const form = h(
    "form",
    { class: "settings" },
    h("p", { class: "setting__hint" }, "Connexion par courriel : un code vous est envoyé, vous le tapez une seule fois."),
    field("1. Votre courriel", email),
    h("div", { class: "card__actions" }, h("button", { class: "btn", type: "button", onclick: () => on.emailStart(email.value.trim()) }, "Envoyer le code")),
    field("2. Code reçu", code),
    h("div", { class: "card__actions" }, h("button", { class: "btn btn--primary", type: "submit" }, "Se connecter")),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    on.emailVerify(email.value.trim(), code.value.trim());
  });
  return form;
}

export function pairingForm(on: SettingsHandlers): HTMLElement {
  const code = h("input", {
    name: "code",
    inputmode: "numeric",
    autocomplete: "one-time-code",
    maxlength: 6,
    pattern: "[0-9]{6}",
    spellcheck: "false",
    placeholder: "123456",
  });
  const form = h(
    "form",
    { class: "settings" },
    h("p", { class: "setting__hint" }, "1. Demandez un code : il s'affiche sur le bureau Windows (2 minutes, 5 essais)."),
    h("div", { class: "card__actions" }, h("button", { class: "btn", type: "button", onclick: () => on.pairStart() }, "Demander un code")),
    field("2. Code affiché", code),
    h(
      "div",
      { class: "card__actions" },
      h("button", { class: "btn btn--primary", type: "submit" }, "Coupler"),
      h("button", { class: "btn btn--ghost", type: "button", onclick: () => on.unpair() }, "Oublier le couplage"),
    ),
    h(
      "p",
      { class: "setting__hint" },
      "Pas de code sur le bureau ? Voir « omniscient group pair » dans un terminal que vous ouvrez vous-même.",
    ),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    on.pairFinish(code.value.trim());
  });
  return form;
}

export function settingsView(
  current: Settings,
  link: LinkStatus,
  on: SettingsHandlers,
  autostart: boolean | null,
): HTMLElement {
  const url = h("input", { name: "daemon_url", value: current.daemon_url, required: true, spellcheck: "false" });
  const startDaemon = checkbox("start_daemon", current.start_daemon);
  const home = h("input", {
    name: "wsl_home",
    value: current.wsl_home,
    spellcheck: "false",
    placeholder: "~/projects/omniscient",
  });
  const form = h(
    "form",
    { class: "settings" },
    h("p", { class: `notice notice--${link.state}`, role: "status" }, link.message),
    field("Adresse du démon", url, "Local uniquement (127.0.0.1 ou localhost)."),
    h(
      "label",
      { class: "setting setting--check" },
      startDaemon,
      h("span", { class: "setting__label" }, "Démarrer le démon dans WSL s'il ne répond pas"),
    ),
    field("Dossier Omniscient (WSL)", home, "Le widget lance « omniscient group serve » dans ce dossier, et l'arrête en quittant."),
    h("div", { class: "card__actions" }, h("button", { class: "btn", type: "submit" }, "Enregistrer")),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    on.save({ daemon_url: url.value.trim(), start_daemon: startDaemon.checked, wsl_home: home.value.trim() });
  });
  return h(
    "section",
    { class: "panel", "aria-label": "Réglages" },
    h(
      "header",
      { class: "bar" },
      h("button", { class: "icon-btn", "aria-label": "Retour", title: "Retour (Échap)", onclick: on.back }, "←"),
      h("h1", { class: "bar__title" }, "Réglages"),
      windowControls("large", { toggle: on.collapse }),
    ),
    h(
      "div",
      { class: "panel__body" },
      form,
      h("h2", { class: "section-title" }, "Démarrage"),
      startupSection(autostart, on),
      h(
        "div",
        { class: "card__actions" },
        h("button", { class: "btn", type: "button", onclick: () => on.wizard() }, "Relancer l'assistant"),
        h("span", { class: "setting__hint" }, current.wizard_done === true ? "Assistant déjà passé." : "Assistant pas encore passé."),
      ),
      h("div", { class: "card__actions" }, h("button", { class: "btn", type: "button", onclick: () => on.about() }, "À propos")),
      h("h2", { class: "section-title" }, "Connexion"),
      emailForm(on),
      h("h2", { class: "section-title" }, "Couplage (secours, sans courriel)"),
      pairingForm(on),
    ),
  );
}
