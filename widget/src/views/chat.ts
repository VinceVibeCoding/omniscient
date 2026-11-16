// Chat tab (mode A): talk to Claude Code from the widget. The daemon runs a headless
// Claude session in the chosen project and streams its replies; its tool permissions are
// shown right above the reply box (and in the Sessions tab), answered in place.
import { h } from "../dom";
import { age, clip } from "../format";
import type { BrowserPage, Chat, ChatMessage, ChatState, Project, Provider } from "../types";
import { composer, messageLog } from "./messages";

export interface ChatModel {
  projects: readonly Project[];
  providers: readonly Provider[];
  /** The provider a new conversation will use ("claude-code" or a saved provider id). */
  provider: string;
  /** The browser window the person was last in, and whether to attach its page. */
  browser: BrowserPage | null;
  attachBrowser: boolean;
  chats: readonly Chat[];
  project: string;
  activeId: string | null;
  active: Chat | null;
  messages: readonly ChatMessage[];
  draft: string;
  busy: boolean;
}

export interface ChatHandlers {
  open(chatId: string): void;
  close(): void;
  setProject(name: string): void;
  setProvider(id: string): void;
  setAttachBrowser(attach: boolean): void;
  setDraft(text: string): void;
  send(text: string): void;
  stop(): void;
  refresh(): void;
}

const STATE_LABEL: Record<ChatState, string> = { running: "en cours", idle: "prête", error: "erreur" };
const CHIP: Record<ChatState, string> = { running: "working", idle: "idle", error: "error" };

/** Claude Code always works; another provider needs its key (unless local) and a model. */
export function providerReady(p: Provider): boolean {
  return p.builtin || (p.model !== "" && (p.has_key || p.kind === "openai-compatible"));
}

function providerPicker(m: ChatModel, on: ChatHandlers): HTMLElement | null {
  if (m.providers.length <= 1) return null; // only Claude Code: nothing to choose
  const select = h("select", { class: "chat__project", "aria-label": "Fournisseur IA" });
  for (const p of m.providers) {
    const option = h("option", { value: p.id, disabled: !providerReady(p) }, providerReady(p) ? p.label : `${p.label} (à configurer)`);
    option.selected = p.id === m.provider;
    select.append(option);
  }
  select.addEventListener("change", () => on.setProvider(select.value));
  return h("label", { class: "chat__picker" }, h("span", { class: "setting__label" }, "Fournisseur IA"), select);
}

/** True when a new conversation will carry the browser page (and so needs no project). */
export function attachingBrowser(m: ChatModel): boolean {
  return m.attachBrowser && m.browser !== null;
}

/** What identifies a page: its address, else its title. */
export function pageKey(page: BrowserPage | null): string {
  return page ? page.url || page.title : "";
}

/** A follow-up may carry the page when the chat already runs without tools, or on a plain provider. */
export function canAttachToActive(m: ChatModel): boolean {
  return m.active !== null && (m.active.provider !== "claude-code" || m.active.read_only === true);
}

/** True when the next message of the open conversation will carry the current page. */
export function attachingToActive(m: ChatModel): boolean {
  return canAttachToActive(m) && m.attachBrowser && m.browser !== null;
}

/** « Page du navigateur » : ticked by default, what will be attached, or why nothing will. */
function browserRow(m: ChatModel, on: ChatHandlers, follow = false): HTMLElement | null {
  const page = m.browser;
  if (!page) return null;
  const box = h("input", { type: "checkbox", checked: m.attachBrowser, "aria-label": "Joindre la page du navigateur" });
  box.addEventListener("change", () => on.setAttachBrowser(box.checked));
  return h(
    "label",
    { class: "setting setting--check chat__browser", title: page.url },
    box,
    h("span", { class: "setting__label" }, `${follow ? "Joindre la page actuelle" : "Joindre la page du navigateur"} : ${clip(page.title || page.origin, 60)} (${page.origin})`),
  );
}

function projectPicker(m: ChatModel, on: ChatHandlers): HTMLElement {
  const select = h("select", { class: "chat__project", "aria-label": "Projet" });
  if (m.projects.length === 0) select.append(h("option", { value: "" }, "Aucun projet"));
  for (const p of m.projects) {
    const option = h("option", { value: p.name, title: p.path_label }, p.path_label ? `${p.name} — ${p.path_label}` : p.name);
    option.selected = p.name === m.project;
    select.append(option);
  }
  select.addEventListener("change", () => on.setProject(select.value));
  return h("label", { class: "chat__picker" }, h("span", { class: "setting__label" }, "Projet"), select);
}

function chatRow(c: Chat, on: ChatHandlers): HTMLElement {
  return h(
    "li",
    {},
    h(
      "button",
      { class: "row chat__row", type: "button", "data-row": c.chat_id, onclick: () => on.open(c.chat_id) },
      h(
        "span",
        { class: "row__main" },
        h("span", { class: "row__top" }, h("span", { class: "row__title" }, clip(c.title, 60)), h("span", { class: "row__age" }, age(c.updated_at))),
        h("span", { class: "row__sub" }, h("span", { class: `chip chip--${CHIP[c.state]}` }, STATE_LABEL[c.state]), h("span", { class: "row__cwd" }, c.project)),
      ),
    ),
  );
}

function home(m: ChatModel, on: ChatHandlers): (HTMLElement | null)[] {
  return [
    h(
      "p",
      { class: "setting__hint" },
      attachingBrowser(m)
        ? "Nouvelle conversation avec la page du navigateur : elle répond sans outils (une page web n'est pas fiable)."
        : m.provider === "claude-code"
          ? "Nouvelle conversation avec Claude Code dans le projet choisi."
          : "Nouvelle conversation : un simple échange, sans outils ni accès à vos fichiers.",
    ),
    providerPicker(m, on),
    browserRow(m, on),
    m.provider === "claude-code" && !attachingBrowser(m) ? projectPicker(m, on) : null,
    composer({
      key: "chat-new",
      placeholder: m.provider === "claude-code" ? "Demander quelque chose à Claude…" : "Écrire votre message…",
      label: "Premier message",
      draft: m.draft,
      busy: m.busy || (m.provider === "claude-code" && m.projects.length === 0),
      onDraft: on.setDraft,
      onSend: on.send,
    }),
    h(
      "div",
      { class: "chat__list-head" },
      h("h2", { class: "section-title" }, "Conversations"),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Actualiser", title: "Actualiser", onclick: on.refresh }, "↻"),
    ),
    m.chats.length === 0
      ? h("p", { class: "empty" }, "Aucune conversation pour l'instant.")
      : h("ul", { class: "list" }, ...m.chats.map((c) => chatRow(c, on))),
  ];
}

/** Who answers in the active chat: « Claude », or the provider's name. */
function assistantName(m: ChatModel): string {
  const id = m.active?.provider ?? "claude-code";
  return id === "claude-code" ? "Claude" : (m.providers.find((p) => p.id === id)?.label ?? id);
}

/** « omniscient » for a Claude Code chat, the provider's name for a plain one. */
function conversationWhere(m: ChatModel): string {
  const active = m.active;
  if (!active || active.provider === "claude-code") return active?.project ?? "";
  return m.providers.find((p) => p.id === active.provider)?.label ?? active.provider;
}

/** The box above the answer field: attach the page the person is on now, or why it can't be. */
function followUpPage(m: ChatModel, on: ChatHandlers): HTMLElement | null {
  if (!m.browser) return null;
  if (canAttachToActive(m)) return browserRow(m, on, true);
  return h("p", { class: "setting__hint chat__browser" }, "Cette conversation utilise des outils : démarrez-en une nouvelle pour y joindre une page web.");
}

function conversation(m: ChatModel, on: ChatHandlers, approvals: HTMLElement): (HTMLElement | null)[] {
  const running = m.active?.state === "running";
  return [
    h(
      "div",
      { class: "chat__bar" },
      h("button", { class: "btn btn--ghost", type: "button", onclick: on.close }, "← Conversations"),
      m.active ? h("span", { class: `chip chip--${CHIP[m.active.state]}` }, STATE_LABEL[m.active.state]) : null,
      running ? h("button", { class: "btn btn--danger", type: "button", onclick: on.stop }, "Arrêter") : null,
    ),
    m.active ? h("p", { class: "meta" }, `${clip(m.active.title, 80)} · ${conversationWhere(m)}`) : null,
    messageLog(m.messages, "Envoi en cours…", "chat", assistantName(m)),
    approvals,
    followUpPage(m, on),
    composer({
      key: `chat-${m.activeId ?? ""}`,
      placeholder: running ? `${assistantName(m)} répond… (vous pouvez préparer la suite)` : "Répondre…",
      label: "Message à Claude",
      draft: m.draft,
      busy: m.busy || running,
      onDraft: on.setDraft,
      onSend: on.send,
    }),
  ];
}

/** `approvals`: the chat session's open permission cards (main.ts refreshes it in place). */
export function chatView(m: ChatModel, on: ChatHandlers, head: HTMLElement, approvals: HTMLElement): HTMLElement {
  const body = m.activeId ? conversation(m, on, approvals) : home(m, on);
  return h("section", { class: "panel panel--chat", "aria-label": "Chat" }, head, h("div", { class: "panel__body chat" }, ...body));
}
