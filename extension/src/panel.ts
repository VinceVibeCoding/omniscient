// The side panel: pairing (same 6-digit code as the widget), consent per site, the
// provider, and the conversation. The daemon is only sent the token after it proved it
// knows it; the page is only read for a site the person allowed, and only when they ask.
import { Daemon, type ChatMessage, type ChatView } from "./lib/daemon.js";
import { capturePage, isExcluded, setExcluded } from "./lib/page.js";
import { DAEMON_DEFAULT, pickTab, shareableOrigin, validDaemonUrl } from "./lib/util.js";

interface Provider { id: string; label: string; ready: boolean }
interface Project { name: string; label: string }

const POLL_MS = 1500;
const TEXT_MAX = 20_000;
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

let daemon: Daemon | null = null;
let tab: chrome.tabs.Tab | null = null;
let chatId: string | null = null;
let readOnly = false;
let pollTimer: number | undefined;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text; // never innerHTML: daemon and page text stay text
  return node;
}

function status(message: string, error = false): void {
  const node = $("status");
  node.textContent = message;
  node.classList.toggle("status--err", error);
}

function fail(err: unknown): void {
  status(err instanceof Error ? err.message : String(err), true);
}

function link(on: boolean | null): void {
  $("link").className = `link ${on === null ? "" : on ? "link--on" : "link--off"}`;
}

// ---- storage and pairing -------------------------------------------------------------

async function stored(): Promise<{ base: string; token: string | null }> {
  const data = await chrome.storage.local.get(["base", "token"]);
  const base = typeof data.base === "string" && validDaemonUrl(data.base) ? data.base : DAEMON_DEFAULT;
  return { base, token: typeof data.token === "string" ? data.token : null };
}

function showPairing(base: string, why = ""): void {
  $("main").hidden = true;
  $("pair").hidden = false;
  $<HTMLInputElement>("daemon").value = base;
  link(false);
  if (why) status(why, true);
}

async function pairStart(): Promise<void> {
  const base = validDaemonUrl($<HTMLInputElement>("daemon").value);
  if (!base) return status("Adresse du démon invalide (http://127.0.0.1:<port>).", true);
  await chrome.storage.local.set({ base });
  await new Daemon(base, null).pairStart();
  status("Code affiché sur le bureau Windows : tapez-le ci-dessous.");
}

async function pairFinish(): Promise<void> {
  const code = $<HTMLInputElement>("pair-code").value.trim();
  if (!/^[0-9]{6}$/.test(code)) return status("Le code fait 6 chiffres.", true);
  const { base } = await stored();
  const token = await new Daemon(base, null).pairFinish(code);
  await chrome.storage.local.set({ token });
  $<HTMLInputElement>("pair-code").value = "";
  status("Extension couplée.");
  await start();
}

// ---- the current page ------------------------------------------------------------------

/** The page in the active tab: attached by default, unless unticked for this page. */
async function refreshSite(): Promise<void> {
  const self = `chrome-extension://${chrome.runtime.id}`;
  const focused = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  tab = pickTab(focused, self) ?? pickTab(await chrome.tabs.query({ active: true }), self);
  const origin = shareableOrigin(tab?.url, daemon?.base ?? DAEMON_DEFAULT);
  const excluded = await isExcluded(tab);
  const attach = $<HTMLInputElement>("attach");
  attach.disabled = !origin || chatId !== null;
  attach.checked = Boolean(origin) && !excluded;
  const box = $("site");
  box.replaceChildren();
  if (!origin) {
    box.append(el("p", "site-off", "Cette page ne peut pas être jointe (page du navigateur, ou du démon)."));
    $("attach-label").textContent = "Joindre cette page";
  } else {
    box.append(
      el("p", excluded ? "site-off" : "site-on", excluded ? `Page non jointe : ${origin}` : `Page jointe à vos questions : ${origin}`),
      el("p", "", "Texte, sélection, erreurs de console et requêtes en échec, envoyés seulement quand vous cliquez sur Envoyer. Décochez « Joindre cette page » pour la garder pour vous."),
    );
    $("attach-label").textContent = `Joindre cette page (${origin})`;
  }
  refreshProjectRow();
}

// ---- providers and projects ----------------------------------------------------------------

function asProviders(raw: unknown): { list: Provider[]; preferred: string } {
  const data = raw as { providers?: unknown; default?: unknown };
  const list = (Array.isArray(data.providers) ? data.providers : []).flatMap((p: Record<string, unknown>) => {
    if (typeof p.id !== "string") return [];
    const ready = p.builtin === true || (typeof p.model === "string" && p.model !== "" && (p.has_key === true || p.kind === "openai-compatible"));
    return [{ id: p.id, label: typeof p.label === "string" ? p.label : p.id, ready }];
  });
  return { list, preferred: typeof data.default === "string" ? data.default : "claude-code" };
}

async function loadChoices(): Promise<void> {
  if (!daemon) return;
  const [providers, projects] = await Promise.all([daemon.providers(), daemon.projects()]);
  const { list, preferred } = asProviders(providers);
  const select = $<HTMLSelectElement>("provider");
  select.replaceChildren(...list.map((p) => {
    const option = el("option", "", p.ready ? p.label : `${p.label} (à configurer)`);
    option.value = p.id;
    option.disabled = !p.ready;
    option.selected = p.id === preferred && p.ready;
    return option;
  }));
  const names = ((projects as { projects?: unknown }).projects as Record<string, unknown>[] | undefined ?? []).flatMap((p): Project[] =>
    typeof p.name === "string" ? [{ name: p.name, label: typeof p.path_label === "string" ? p.path_label : p.name }] : []);
  $<HTMLSelectElement>("project").replaceChildren(...names.map((p) => {
    const option = el("option", "", `${p.name} — ${p.label}`);
    option.value = p.name;
    return option;
  }));
  refreshProjectRow();
}

/** Claude Code needs a project unless a page is attached (then it has no tool at all). */
function refreshProjectRow(): void {
  const claude = $<HTMLSelectElement>("provider").value === "claude-code";
  $("project-row").hidden = !(claude && !$<HTMLInputElement>("attach").checked && chatId === null);
}

// ---- conversation --------------------------------------------------------------------------

function renderLog(view: ChatView | null): void {
  const label = $<HTMLSelectElement>("provider").selectedOptions[0]?.textContent ?? "Assistant";
  const who: Record<ChatMessage["role"], string> = { user: "Vous", assistant: label, tool: "Outil", error: "Erreur" };
  $("log").replaceChildren(...(view?.messages ?? []).map((m) => {
    const item = el("li", `msg msg--${m.role}`);
    item.append(el("span", "who", m.role === "tool" && m.tool ? `${who.tool} · ${m.tool}` : who[m.role] ?? m.role), document.createTextNode(m.text));
    return item;
  }));
  $("log").lastElementChild?.scrollIntoView({ block: "end" });
}

function poll(): void {
  window.clearTimeout(pollTimer);
  if (!daemon || !chatId) return;
  const id = chatId;
  daemon.getChat(id).then((view) => {
    if (id !== chatId) return;
    readOnly = view.chat.read_only;
    renderLog(view);
    const running = view.chat.state === "running";
    $<HTMLButtonElement>("send").disabled = running;
    status(running ? "Réponse en cours…" : readOnly ? "Conversation sans outils (une page y est jointe)." : "");
    if (running) pollTimer = window.setTimeout(poll, POLL_MS);
  }).catch(fail);
}

async function send(event: Event): Promise<void> {
  event.preventDefault();
  if (!daemon) return;
  const area = $<HTMLTextAreaElement>("text");
  const text = area.value.trim();
  if (!text) return;
  if (text.length > TEXT_MAX) return status(`Message trop long (${TEXT_MAX} caractères au plus).`, true);
  $<HTMLButtonElement>("send").disabled = true;
  try {
    if (chatId) {
      await daemon.sendChat(chatId, text);
    } else {
      const provider = $<HTMLSelectElement>("provider").value;
      const attach = $<HTMLInputElement>("attach").checked;
      const page = attach && tab ? await capturePage(tab, daemon.base) : undefined;
      const project = provider === "claude-code" && !page ? $<HTMLSelectElement>("project").value : undefined;
      chatId = await daemon.createChat({ text, provider, ...(project ? { project } : {}), ...(page ? { page } : {}) });
      $<HTMLInputElement>("attach").disabled = true;
      $<HTMLSelectElement>("provider").disabled = true;
      refreshProjectRow();
    }
    area.value = "";
    poll();
  } catch (err) {
    $<HTMLButtonElement>("send").disabled = false;
    fail(err);
  }
}

function newChat(): void {
  window.clearTimeout(pollTimer);
  chatId = null;
  readOnly = false;
  renderLog(null);
  $<HTMLSelectElement>("provider").disabled = false;
  $<HTMLButtonElement>("send").disabled = false;
  status("");
  void refreshSite();
}

// ---- start-up --------------------------------------------------------------------------------

async function start(): Promise<void> {
  const { base, token } = await stored();
  if (!token) return showPairing(base);
  const candidate = new Daemon(base, token);
  let known = false;
  try {
    known = await candidate.verify();
  } catch (err) {
    link(false);
    return fail(err);
  }
  if (!known) return showPairing(base, "Ce démon ne reconnaît pas l'extension : recouplez-la.");
  daemon = candidate;
  link(true);
  $("pair").hidden = true;
  $("main").hidden = false;
  await loadChoices();
  await refreshSite();
}

function wire(): void {
  $("pair-start").addEventListener("click", () => void pairStart().catch(fail));
  $("pair-finish").addEventListener("click", () => void pairFinish().catch(fail));
  $("composer").addEventListener("submit", (e) => void send(e));
  $("new-chat").addEventListener("click", newChat);
  $("provider").addEventListener("change", refreshProjectRow);
  $("attach").addEventListener("change", () => {
    const ticked = $<HTMLInputElement>("attach").checked;
    if (tab) void setExcluded(tab, !ticked).then(refreshSite).catch(fail); // for this page only
    refreshProjectRow();
  });
  chrome.tabs.onActivated.addListener(() => void refreshSite().catch(fail));
  chrome.tabs.onUpdated.addListener((_id, info) => info.status === "complete" && void refreshSite().catch(fail));
}

wire();
start().catch(fail);
