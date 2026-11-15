// « Compte »: sign in with Google, GitHub, or an e-mail and a password. The browser opens
// for Google / GitHub; the e-mail form is local. The password field is emptied once sent
// and never kept. An account carries identity only: keys and chats stay on this computer.
import { h } from "../dom";
import type { AccountHandlers, AccountModel } from "../account-controller";
import type { AuthProvider } from "../types";

const PROVIDER_LABEL: Record<string, string> = { google: "Google", github: "GitHub", email: "e-mail" };

function signedIn(m: AccountModel, on: AccountHandlers): HTMLElement {
  const user = m.status.user;
  const via = PROVIDER_LABEL[user?.provider ?? "email"] ?? "e-mail";
  return h(
    "div",
    { class: "acct__me" },
    h("p", { class: "notice notice--connected", role: "status" }, `Connecté : ${user?.name || user?.email} (${via})`),
    user?.name ? h("p", { class: "setting__hint" }, user.email) : null,
    h("div", { class: "card__actions" }, h("button", { class: "btn btn--ghost", type: "button", disabled: m.busy, onclick: () => on.signout() }, "Se déconnecter")),
  );
}

function providerButton(provider: AuthProvider, m: AccountModel, on: AccountHandlers): HTMLElement {
  return h(
    "button",
    { class: "btn acct__provider", type: "button", disabled: m.busy, onclick: () => on.start(provider) },
    `Continuer avec ${PROVIDER_LABEL[provider]}`,
  );
}

function emailForm(m: AccountModel, on: AccountHandlers): HTMLElement {
  const signup = m.draft.mode === "signup";
  const email = h("input", { name: "email", type: "email", value: m.draft.email, autocomplete: "email", spellcheck: "false", placeholder: "vous@exemple.com", "aria-label": "Adresse e-mail" });
  const password = h("input", {
    name: "password",
    type: "password",
    autocomplete: signup ? "new-password" : "current-password",
    placeholder: "Mot de passe (8 caractères au moins)",
    "aria-label": "Mot de passe",
  });
  email.addEventListener("input", () => on.setDraft({ email: email.value }));
  const form = h(
    "form",
    { class: "settings acct__form" },
    h("label", { class: "setting" }, h("span", { class: "setting__label" }, "E-mail"), email),
    h("label", { class: "setting" }, h("span", { class: "setting__label" }, "Mot de passe"), password),
    h("div", { class: "card__actions" }, h("button", { class: "btn btn--primary", type: "submit", disabled: m.busy }, signup ? "Créer le compte" : "Se connecter")),
    h(
      "button",
      { class: "btn btn--ghost acct__switch", type: "button", onclick: () => on.setMode(signup ? "signin" : "signup") },
      signup ? "J'ai déjà un compte" : "Créer un compte",
    ),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    on.password(m.draft.mode, email.value.trim(), password.value);
    password.value = ""; // the password leaves the page as soon as it is sent
    password.blur(); // a focused field holds redraws back: let the result show
  });
  return form;
}

export function accountSection(m: AccountModel, on: AccountHandlers): HTMLElement {
  const s = m.status;
  let body: (HTMLElement | null)[];
  if (s.signed_in) body = [signedIn(m, on)];
  else if (!s.configured) {
    body = [h("p", { class: "setting__hint" }, "Les comptes ne sont pas configurés sur ce démon (voir docs/accounts.md). Le widget fonctionne très bien sans compte.")];
  } else {
    body = [
      h("p", { class: "setting__hint" }, "Facultatif : un compte identifie cette installation. Vos clés et vos conversations restent sur cet ordinateur."),
      ...s.providers.map((p) => providerButton(p, m, on)),
      s.pending ? h("p", { class: "notice", role: "status" }, "Terminez la connexion dans votre navigateur… Elle expire au bout de 10 minutes.") : null,
      h("p", { class: "setting__hint acct__or" }, "ou avec une adresse e-mail"),
      emailForm(m, on),
      s.message ? h("p", { class: "notice", role: "status" }, s.message) : null,
    ];
  }
  return h("section", { class: "acct", "aria-label": "Compte" }, ...body, m.error ? h("p", { class: "notice notice--error", role: "alert" }, m.error) : null);
}
