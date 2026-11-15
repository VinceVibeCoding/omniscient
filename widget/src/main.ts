// Omnigroup widget: state, rendering and wiring to the Rust side.
import { listen } from "@tauri-apps/api/event";
import * as api from "./api";
import * as osdApi from "./api-osd";
import { ChatController } from "./chat-controller";
import { AccountController } from "./account-controller";
import * as providerApi from "./api-providers";
import { ProviderController } from "./provider-controller";
import { accountSection } from "./views/account";
import { providersSection } from "./views/providers";
import { wizardView } from "./views/wizard";
import { h, replace } from "./dom";
import { installDrag } from "./drag";
import { installResize } from "./resize";
import { keepUiState, restoreUiState } from "./keep";
import { applySkin, applyTheme } from "./theme";
import type { ConfigPatch, Skin, ConfigView, LinkStatus, Osd, Pending, Session, SessionDetail, Settings, Step, StreamEvent, Transcript, Usage, WidgetConfig } from "./types";
import { chatView } from "./views/chat";
import { detailView } from "./views/detail";
import { displaySection } from "./views/display";
import { header, listView } from "./views/list";
import { osdView } from "./views/osd";
import { settingsView } from "./views/settings";
import { type Tab, tabBar, withTabs } from "./views/tabs";
import { transcriptSection } from "./views/transcript";
import { pendingCard } from "./views/pending";
import { STRIP_CLASS, usageStrip, withUsageStrip } from "./views/usage-strip";

type View = "osd" | "list" | "detail" | "settings" | "chat" | "wizard";

interface AppState {
  readonly view: View;
  readonly sessions: readonly Session[];
  readonly detail: SessionDetail | null;
  readonly transcript: Transcript | null;
  readonly settings: Settings | null;
  readonly link: LinkStatus;
  readonly osd: Osd | null;
  readonly config: ConfigView | null;
  readonly autostart: boolean | null;
  readonly wizardStep: number;
}

const REFRESH_DEBOUNCE_MS = 250;
const AGE_TICK_MS = 30_000;
const TOAST_MS = 4_000;
const CHAT_APPROVALS = "chat__approvals";
const DEFAULT_CONFIG: WidgetConfig = { theme: "default", osd_view: "bars", show_ticker: true };
const DEFAULT_SETTINGS: Settings = { daemon_url: "http://127.0.0.1:7341", start_daemon: false, wsl_home: "" };

const app = document.getElementById("app") as HTMLElement;
const toastEl = document.getElementById("toast") as HTMLElement;

let state: AppState = {
  view: "osd",
  sessions: [],
  detail: null,
  transcript: null,
  settings: null,
  link: { state: "connecting", message: "Connexion au démon…" },
  osd: null,
  config: null,
  autostart: null,
  wizardStep: 0,
};
let deferredRender = false;
let refreshTimer: number | undefined;
let transcriptTimer: number | undefined;
let toastTimer: number | undefined;
let sessionDraft = "";

const account = new AccountController(
  () => (state.view === "settings" || state.view === "wizard") && render(),
  (err) => toast(api.errorText(err)),
);

const providers = new ProviderController(
  () => (state.view === "settings" || state.view === "wizard") && render(),
  (err) => toast(api.errorText(err)),
);

const chat = new ChatController(
  () => state.view === "chat" && render(),
  (err) => toast(api.errorText(err)),
);

function update(patch: Partial<AppState>): void {
  state = { ...state, ...patch };
  render();
}

function toast(message: string): void {
  toastEl.textContent = message;
  toastEl.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (toastEl.hidden = true), TOAST_MS);
}

function editing(): boolean {
  const active = document.activeElement;
  // Only a field being typed in holds a redraw back: a focused button (just clicked) must not,
  // or the result of its own action (a new provider row, say) would stay invisible.
  return (
    active instanceof HTMLElement &&
    app.contains(active) &&
    active.matches("input, textarea, select, [contenteditable]") &&
    active.closest("form") !== null
  );
}

function render(): void {
  if (editing()) {
    deferredRender = true;
    refreshInPlace(); // usage and approvals must not wait for the end of typing
    return;
  }
  deferredRender = false;
  document.body.dataset.view = state.view;
  const kept = keepUiState(app);
  const view = viewFor(state);
  replace(app, state.view === "osd" || state.view === "wizard" ? view : withUsageStrip(view, strip()));
  restoreUiState(app, kept);
}

function strip(): HTMLElement {
  return usageStrip(state.osd, state.config?.config.theme ?? "default");
}

/** Panel open: refresh only the usage strip (forms and scroll positions stay as they are). */
function refreshStrip(): void {
  app.querySelector(`.${STRIP_CLASS}`)?.replaceWith(strip());
}

/** Open permission requests of the active widget chat's session, as answerable cards. */
function chatApprovals(): HTMLElement {
  const sid = chat.view.active?.session_id;
  const session = sid ? state.sessions.find((s) => s.id === sid) : undefined;
  const open = session ? session.pending.filter((p) => p.status === "open") : [];
  const handlers = { answer: detailHandlers.answer, jump: () => session && detailHandlers.jump(session.id) };
  const ctx = { title: session?.title || "Chat", cwd: session?.cwd ?? null };
  return h("div", { class: CHAT_APPROVALS, "aria-live": "polite" }, ...open.map((p) => pendingCard(p, ctx, handlers)));
}

function refreshInPlace(): void {
  refreshStrip();
  if (state.view === "chat") app.querySelector(`.${CHAT_APPROVALS}`)?.replaceWith(chatApprovals());
}

function selectTab(tab: Tab): void {
  if (tab === "sessions") update({ view: "list", detail: null, transcript: null });
  else if (tab === "settings") void openSettings();
  else {
    update({ view: "chat" });
    void chat.load();
  }
}

function viewFor(s: AppState): HTMLElement {
  const sessions = [...s.sessions];
  const nav = { open: openSession, collapse, settings: () => selectTab("settings") };
  switch (s.view) {
    case "osd":
      return osdView({ osd: s.osd, config: s.config?.config ?? DEFAULT_CONFIG, link: s.link, sessions }, () => void expand());
    case "detail":
      if (s.detail) return detailView(s.detail, detailHandlers, conversationFor(s.detail, s.transcript));
      return withTabs(listView(sessions, s.link, nav), tabBar("sessions", selectTab));
    case "settings":
      return settingsPanel(s);
    case "wizard":
      return wizardView(
        { step: s.wizardStep, link: s.link, providers: providers.view, account: account.view, skin: s.config?.config.theme ?? "default" },
        wizardHandlers,
      );
    case "chat":
      return withTabs(chatView(chat.view, chat.handlers, header(s.link, nav, "Chat"), chatApprovals()), tabBar("chat", selectTab));
    default:
      return withTabs(listView(sessions, s.link, nav), tabBar("sessions", selectTab));
  }
}

function settingsPanel(s: AppState): HTMLElement {
  const panel = settingsView({ ...DEFAULT_SETTINGS, ...s.settings }, s.link, settingsHandlers, s.autostart);
  const body = panel.querySelector(".panel__body");
  body?.prepend(h("h2", { class: "section-title" }, "Fournisseurs IA"), providersSection(providers.view, providers.handlers));
  body?.prepend(h("h2", { class: "section-title" }, "Compte"), accountSection(account.view, account.handlers));
  body?.prepend(displaySection(s.config, changeConfig));
  return withTabs(panel, tabBar("settings", selectTab));
}

/** Start a widget chat from a copy of `detail`'s session, then show it in the Chat tab. */
async function continueInWidget(detail: SessionDetail, text: string): Promise<void> {
  const started = await chat.fork({ id: detail.id, title: detail.title, cwd: detail.cwd }, text);
  if (!started) return;
  sessionDraft = "";
  update({ view: "chat", detail: null, transcript: null });
  void chat.load();
}

function conversationFor(detail: SessionDetail, transcript: Transcript | null): HTMLElement {
  return transcriptSection(detail.id, transcript, sessionDraft, {
    setDraft: (text) => (sessionDraft = text),
    send: (text) => detailHandlers.prompt(detail.id, text),
    fork: (text) => void continueInWidget(detail, text),
  });
}

const READY_TRIES = 20;
const READY_DELAY_MS = 250;

/** Start-up reads: the webview can load before the Rust side has finished setting up its
 * state, so the first calls may fail for a moment. Retries, then reports the last error. */
async function whenReady<T>(work: () => Promise<T>): Promise<T | undefined> {
  for (let attempt = 1; attempt <= READY_TRIES; attempt += 1) {
    try {
      return await work();
    } catch (err) {
      if (attempt === READY_TRIES) {
        toast(api.errorText(err));
        return undefined;
      }
      await new Promise((resolve) => window.setTimeout(resolve, READY_DELAY_MS));
    }
  }
  return undefined;
}

async function guarded<T>(work: () => Promise<T>): Promise<T | undefined> {
  try {
    return await work();
  } catch (err) {
    toast(api.errorText(err));
    return undefined;
  }
}

async function refreshSessions(): Promise<void> {
  const sessions = await guarded(api.listSessions);
  if (sessions) update({ sessions });
  if (state.view === "detail" && state.detail) {
    const detail = await guarded(() => api.getSession(state.detail?.id ?? ""));
    if (detail) update({ detail });
  }
}

/** Mode B: an older daemon (or a non-Claude session) has no transcript → null, no toast. */
async function loadTranscript(id: string): Promise<void> {
  let transcript: Transcript | null;
  try {
    transcript = await osdApi.sessionTranscript(id);
  } catch {
    transcript = null;
  }
  if (state.detail?.id === id) update({ transcript });
}

function scheduleRefresh(): void {
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => void refreshSessions(), REFRESH_DEBOUNCE_MS);
}

function scheduleTranscript(id: string): void {
  window.clearTimeout(transcriptTimer);
  transcriptTimer = window.setTimeout(() => void loadTranscript(id), REFRESH_DEBOUNCE_MS);
}

async function expand(): Promise<void> {
  await guarded(() => api.setWindowMode("panel"));
  if (state.link.state === "connected") update({ view: "list" });
  else await openSettings();
  app.querySelector<HTMLElement>("[data-row], [role=tab], button")?.focus();
}

function collapse(): void {
  update({ view: "osd", detail: null, transcript: null });
  void guarded(() => api.setWindowMode("osd"));
}

async function openSession(id: string): Promise<void> {
  const detail = await guarded(() => api.getSession(id));
  if (!detail) return;
  sessionDraft = "";
  update({ view: "detail", detail, transcript: null });
  void loadTranscript(id);
  app.querySelector<HTMLElement>(".card button, .card input, .actions button")?.focus();
}

async function openSettings(): Promise<void> {
  const settings = await guarded(api.getSettings);
  const autostart = await guarded(api.getAutostart);
  update({ view: "settings", settings: settings ?? state.settings, autostart: autostart ?? null });
  void providers.load();
  void account.load();
}

/** First run: the assistant (connect → AI provider → look) in the expanded panel. */
async function startWizard(): Promise<void> {
  await whenReady(() => api.setWindowMode("panel"));
  const link = (await whenReady(api.linkStatus)) ?? state.link;
  update({ view: "wizard", wizardStep: link.state === "connected" ? 1 : 0 });
  await providers.load();
  await account.load();
}

const wizardHandlers = {
  go: (step: number) => update({ wizardStep: step }),
  finish: () =>
    void guarded(async () => {
      await providerApi.finishWizard();
      update({ view: state.link.state === "connected" ? "list" : "settings", settings: state.settings && { ...state.settings, wizard_done: true } });
    }),
  pair: {
    pairStart: () => settingsHandlers.pairStart(),
    unpair: () => settingsHandlers.unpair(),
    pairFinish: (code: string) =>
      void guarded(async () => {
        if (!/^[0-9]{6}$/.test(code)) {
          toast("Le code de couplage fait 6 chiffres.");
          return;
        }
        toast(await api.pairFinish(code));
        (document.activeElement as HTMLElement | null)?.blur();
        render(); // stays in the assistant: the link event moves the step forward
      }),
  },
  providers: providers.handlers,
  account: account.handlers,
  setSkin: (skin: Skin) => changeConfig({ theme: skin }),
};

function applyConfig(view: ConfigView | null): void {
  if (!view) return;
  applySkin(view.config.theme);
  update({ config: view });
}

function changeConfig(patch: ConfigPatch): void {
  void guarded(async () => applyConfig(await osdApi.setConfig(patch)));
}

const detailHandlers = {
  back: () => update({ view: "list", detail: null, transcript: null }),
  answer: (pending: Pending, answer: api.Answer) =>
    void guarded(async () => {
      await api.answerPending(pending.id, answer);
      toast("Réponse envoyée.");
      await refreshSessions();
    }),
  jump: (id: string) =>
    void guarded(async () => {
      const res = await api.jumpSession(id);
      toast(res.message);
    }),
  dismiss: (id: string) =>
    void guarded(async () => {
      await api.dismissSession(id);
      update({ view: "list", detail: null, transcript: null, sessions: state.sessions.filter((s) => s.id !== id) });
    }),
  prompt: (id: string, text: string) =>
    void guarded(async () => {
      const res = await api.promptSession(id, text);
      toast(res.message);
      sessionDraft = "";
      (document.activeElement as HTMLElement | null)?.blur();
      await refreshSessions();
      scheduleTranscript(id);
    }),
};

const settingsHandlers = {
  back: () => update({ view: "list" }),
  wizard: () => void startWizard(),
  autostart: (enabled: boolean) =>
    void guarded(async () => {
      const now = await api.setAutostart(enabled);
      toast(now ? "Omnigroup se lancera au démarrage de Windows." : "Lancement au démarrage désactivé.");
      update({ autostart: now });
    }),
  save: (settings: Settings) =>
    void guarded(async () => {
      const saved = await api.saveSettings(settings);
      toast("Réglages enregistrés.");
      (document.activeElement as HTMLElement | null)?.blur();
      update({ settings: saved, view: "list" });
    }),
  pairStart: () =>
    void guarded(async () => {
      toast(await api.pairStart());
    }),
  pairFinish: (code: string) =>
    void guarded(async () => {
      if (!/^[0-9]{6}$/.test(code)) {
        toast("Le code de couplage fait 6 chiffres.");
        return;
      }
      toast(await api.pairFinish(code));
      (document.activeElement as HTMLElement | null)?.blur();
      update({ view: "list" });
    }),
  unpair: () =>
    void guarded(async () => {
      toast(await api.unpair());
    }),
};

function withUsage<T extends Session>(session: T, id: string, usage: Usage | null): T {
  return session.id === id ? { ...session, usage } : session;
}

function onUsageEvent(data: unknown): void {
  if (typeof data !== "object" || data === null) return;
  const { session_id: id, usage } = data as { session_id?: unknown; usage?: unknown };
  if (typeof id !== "string") return;
  const value = typeof usage === "object" && usage !== null ? (usage as Usage) : null;
  update({
    sessions: state.sessions.map((s) => withUsage(s, id, value)),
    detail: state.detail ? withUsage(state.detail, id, value) : null,
  });
}

function onOsd(data: unknown): void {
  const osd = osdApi.toOsd(data);
  if (!osd) return;
  if (state.view === "osd") update({ osd });
  else {
    state = { ...state, osd }; // no full re-render of an open panel every 2 s
    refreshStrip();
  }
}

function onStreamEvent(event: StreamEvent): void {
  switch (event.type) {
    case "osd":
      return onOsd(event.data);
    case "config":
      return applyConfig(osdApi.toConfigView(event.data));
    case "auth":
      return account.onEvent(event.data);
    case "chat": {
      const chatEvent = osdApi.toChatEvent(event.data);
      if (chatEvent) chat.onEvent(chatEvent);
      return;
    }
    case "usage":
      return onUsageEvent(event.data);
    case "menu_error": {
      const data = event.data as { message?: unknown } | null;
      if (data && typeof data.message === "string") toast(data.message);
      return;
    }
  }
  if (event.type === "step" && state.detail) {
    const step = event.data as Step;
    if (step && step.session_id === state.detail.id) {
      update({ detail: { ...state.detail, steps: [...state.detail.steps, step] } });
      scheduleTranscript(state.detail.id);
    }
  }
  scheduleRefresh();
}

async function onLink(link: LinkStatus): Promise<void> {
  update({ link });
  if (link.state !== "connected") return;
  const theme = await guarded(api.getTheme);
  if (theme !== undefined) applyTheme(theme);
  applyConfig((await guarded(osdApi.getConfig)) ?? null);
  const osd = await guarded(osdApi.getOsd);
  if (osd) update({ osd });
  await refreshSessions();
}

function onKey(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  if (state.view === "chat" && chat.view.activeId) chat.handlers.close();
  else if (state.view === "detail" || state.view === "settings" || state.view === "chat") update({ view: "list", detail: null, transcript: null });
  else if (state.view === "list") collapse();
}

/** Right-click anywhere on the widget (OSD or expanded panel) opens its own menu (menu.html:
 * OSD View, Thème, Taille, ticker…). Text fields and selected text keep the native
 * copy / paste menu. */
function onContextMenu(event: MouseEvent): void {
  const target = event.target as Element | null;
  if (target?.closest("input, textarea, select, [contenteditable]")) return;
  if ((window.getSelection()?.toString() ?? "") !== "") return;
  event.preventDefault();
  void guarded(osdApi.showContextMenu);
}

async function main(): Promise<void> {
  applySkin("default");
  render();
  document.addEventListener("keydown", onKey);
  document.addEventListener("contextmenu", onContextMenu);
  installDrag(document, api.startDrag);
  const grip = document.getElementById("grip");
  if (grip) {
    const resizeApi = { start: api.resizeStart, move: api.resizeMove, end: api.resizeEnd, get: api.getScale, set: api.setScale };
    installResize(grip, resizeApi, (err) => toast(api.errorText(err)));
  }
  app.addEventListener("focusout", () => window.setTimeout(() => deferredRender && render(), 0));
  window.setInterval(() => state.view !== "detail" && state.view !== "chat" && render(), AGE_TICK_MS);
  await listen<StreamEvent>("group://event", (e) => onStreamEvent(e.payload));
  await listen<LinkStatus>("group://status", (e) => void onLink(e.payload));
  await listen<string>("group://open", (e) => (e.payload ? void openSession(e.payload) : void expand()));
  const settings = await whenReady(api.getSettings);
  if (settings) state = { ...state, settings };
  // First run: the assistant opens as soon as the settings are known, without waiting for
  // the daemon link (which may take a few seconds, or never come when nothing is paired).
  const wizard = settings && settings.wizard_done !== true ? startWizard() : Promise.resolve();
  const link = await whenReady(api.linkStatus);
  if (link) await onLink(link);
  await wizard;
}

main().catch((err: unknown) => {
  console.error("omnigroup: start-up failed", err);
});
