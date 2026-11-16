// State and actions of the Chat tab (mode A). Owns its own immutable model and calls
// `changed()` so main.ts re-renders. Streamed `chat` events are appended at once, then
// the conversation is re-read from the daemon when a turn ends (source of truth).
import * as osdApi from "./api-osd";
import * as providerApi from "./api-providers";
import type { Chat, ChatEvent, ChatMessage, Provider } from "./types";
import { attachingBrowser, attachingToActive, pageKey, providerReady } from "./views/chat";
import type { ChatHandlers, ChatModel } from "./views/chat";

const RELOAD_DEBOUNCE_MS = 300;

export class ChatController {
  private model: ChatModel = {
    projects: [],
    providers: [],
    provider: "claude-code",
    browser: null,
    attachBrowser: true,
    chats: [],
    project: "",
    activeId: null,
    active: null,
    messages: [],
    draft: "",
    busy: false,
  };
  private reloadTimer: number | undefined;
  readonly handlers: ChatHandlers;

  constructor(
    private readonly changed: () => void,
    private readonly fail: (err: unknown) => void,
  ) {
    this.handlers = {
      open: (id) => void this.open(id),
      close: () => this.set({ activeId: null, active: null, messages: [], draft: "", attachBrowser: true }),
      setProject: (project) => this.set({ project }),
      setProvider: (provider) => this.set({ provider }),
      setAttachBrowser: (attachBrowser) => this.set({ attachBrowser }),
      setDraft: (draft) => {
        this.model = { ...this.model, draft }; // no re-render while typing
      },
      send: (text) => void this.send(text),
      stop: () => void this.stop(),
      refresh: () => void this.load(),
    };
  }

  get view(): ChatModel {
    return this.model;
  }

  private set(patch: Partial<ChatModel>): void {
    this.model = { ...this.model, ...patch };
    this.changed();
  }

  private async guard(work: () => Promise<void>): Promise<void> {
    try {
      await work();
    } catch (err) {
      this.set({ busy: false });
      this.fail(err);
    }
  }

  /** Projects + conversation list (called when the Chat tab opens). */
  async load(): Promise<void> {
    await this.guard(async () => {
      const [projects, chats, list, browser] = await Promise.all([
        osdApi.listProjects(),
        osdApi.chatList(),
        providerApi.listProviders(),
        osdApi.getBrowserPage().catch(() => null), // an older daemon has no browser page
      ]);
      const project = projects.some((p) => p.name === this.model.project) ? this.model.project : (projects[0]?.name ?? "");
      const active = chats.find((c) => c.chat_id === this.model.activeId) ?? this.model.active;
      const providers = list.providers;
      this.set({ projects, chats, project, active, providers, browser, provider: this.pickProvider(providers, list.default) });
    });
  }

  /** Keeps the person's choice while it is still usable, else their default, else Claude Code. */
  private pickProvider(providers: readonly Provider[], preferred: string): string {
    const usable = (id: string): boolean => providers.some((p) => p.id === id && providerReady(p));
    if (usable(this.model.provider) && this.model.provider !== "claude-code") return this.model.provider;
    return usable(preferred) ? preferred : "claude-code";
  }

  private async open(chatId: string): Promise<void> {
    this.set({ activeId: chatId, messages: [], draft: "" });
    await this.reload();
    // The page is offered again when it is not the one this conversation already has.
    this.set({ attachBrowser: pageKey(this.model.browser) !== (this.model.active?.page_key ?? "") });
  }

  private async reload(): Promise<void> {
    const id = this.model.activeId;
    if (!id) return;
    await this.guard(async () => {
      const { chat, messages } = await osdApi.chatGet(id);
      if (this.model.activeId !== id) return;
      this.set({ active: chat ?? this.model.active, messages });
    });
  }

  private scheduleReload(): void {
    window.clearTimeout(this.reloadTimer);
    this.reloadTimer = window.setTimeout(() => {
      void this.reload();
      void this.refreshList();
    }, RELOAD_DEBOUNCE_MS);
  }

  private async refreshList(): Promise<void> {
    await this.guard(async () => this.set({ chats: await osdApi.chatList() }));
  }

  private userMessage(text: string): ChatMessage {
    return { role: "user", text, at: new Date().toISOString() };
  }

  private async send(text: string): Promise<void> {
    const id = this.model.activeId;
    this.set({ busy: true, draft: "", messages: [...this.model.messages, this.userMessage(text)] });
    await this.guard(async () => {
      if (id) {
        const attach = attachingToActive(this.model);
        await osdApi.chatSend(id, text, attach);
        if (attach && this.model.active) {
          // This page is now in the conversation: offer the next one, not this one again.
          this.set({ active: { ...this.model.active, page_key: pageKey(this.model.browser) }, attachBrowser: false });
        }
      } else {
        const provider = this.model.provider;
        const claude = provider === "claude-code";
        const browserPage = attachingBrowser(this.model);
        if (claude && !browserPage && !this.model.project) throw new Error("Choisissez un projet.");
        const target = browserPage ? { provider, browserPage } : claude ? { project: this.model.project, provider } : { provider };
        const chatId = await osdApi.chatCreate(text, target);
        const now = new Date().toISOString();
        const active: Chat = {
          chat_id: chatId,
          provider,
          project: claude ? this.model.project : "",
          title: text.slice(0, 80),
          state: "running",
          updated_at: now,
          session_id: null,
          read_only: browserPage,
          page_key: browserPage ? pageKey(this.model.browser) : "",
        };
        this.set({ activeId: chatId, active, ...(browserPage ? { attachBrowser: false } : {}) });
      }
      this.set({ busy: false });
    });
  }

  /** « Continuer dans le widget »: a widget chat that starts from a copy of a session. */
  async fork(session: { id: string; title: string; cwd: string | null }, text: string): Promise<boolean> {
    this.set({ busy: true });
    let ok = false;
    await this.guard(async () => {
      const chatId = await osdApi.chatFork(session.id, text);
      const now = new Date().toISOString();
      const active: Chat = {
        chat_id: chatId,
        project: session.cwd?.split("/").filter(Boolean).pop() ?? "",
        title: text.slice(0, 80),
        state: "running",
        updated_at: now,
        session_id: null,
        provider: "claude-code",
      };
      this.set({ activeId: chatId, active, messages: [this.userMessage(text)], draft: "", busy: false });
      ok = true;
    });
    return ok;
  }

  private async stop(): Promise<void> {
    const id = this.model.activeId;
    if (id) await this.guard(async () => void (await osdApi.chatStop(id)));
  }

  private withState(event: ChatEvent): Partial<ChatModel> {
    const state = event.state;
    if (!state) return {};
    const chats = this.model.chats.map((c) => (c.chat_id === event.chat_id ? { ...c, state, updated_at: event.at || c.updated_at } : c));
    const active = this.model.active?.chat_id === event.chat_id ? { ...this.model.active, state } : this.model.active;
    return { chats, active };
  }

  private messageFor(event: ChatEvent): ChatMessage | null {
    const at = event.at || new Date().toISOString();
    if (event.kind === "text" && event.text) return { role: "assistant", text: event.text, at };
    if (event.kind === "tool") return { role: "tool", text: event.text ?? "", at, ...(event.tool ? { tool: event.tool } : {}) };
    if (event.kind === "error") return { role: "error", text: event.text ?? "Erreur inconnue.", at };
    return null;
  }

  /** `browser_page`: the widget saw another browser page (title only). A new page starts
   * ticked again. */
  onBrowserPage(raw: unknown): void {
    const browser = osdApi.toBrowserPage(raw);
    const changed = pageKey(browser) !== pageKey(this.model.browser);
    // A new page is offered again: in a conversation, unless it is the page it already has.
    const offered = this.model.activeId ? pageKey(browser) !== (this.model.active?.page_key ?? "") : true;
    this.set(changed ? { browser, attachBrowser: offered } : { browser });
  }

  /** SSE `chat` event from the daemon. */
  onEvent(event: ChatEvent): void {
    const patch = this.withState(event);
    const message = event.chat_id === this.model.activeId ? this.messageFor(event) : null;
    this.set(message ? { ...patch, messages: [...this.model.messages, message] } : patch);
    const known = this.model.chats.some((c) => c.chat_id === event.chat_id);
    // A new chat learns its session id from the daemon once Claude has started: needed
    // to show that session's approvals inline before the turn ends.
    const unlinked = event.chat_id === this.model.activeId && !this.model.active?.session_id;
    if (event.kind === "result" || event.kind === "error" || event.kind === "state" || !known || unlinked) {
      this.scheduleReload();
    }
  }
}
