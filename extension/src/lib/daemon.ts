// The local Omnigroup daemon, as the extension sees it. The token is only ever sent after
// the daemon proved it knows it (proof.ts); every call has a timeout; errors carry the
// daemon's French message.
import { newNonce, proves } from "./proof.js";

const TIMEOUT_MS = 20_000;
export const CLIENT_NAME = "Extension navigateur";

export class DaemonError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool" | "error";
  text: string;
  tool?: string;
}

export interface ChatView {
  chat: { chat_id: string; state: "running" | "idle" | "error"; provider: string; read_only: boolean };
  messages: ChatMessage[];
}

export interface PagePayload {
  url: string;
  title: string;
  text: string;
  selection: string;
  errors: string[];
  network: { method: string; url: string; status: number }[];
}

async function request(base: string, method: string, path: string, token: string | null, body?: unknown): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(`${base}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: "omit",
      cache: "no-store",
    });
    const data: unknown = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = typeof (data as { error?: unknown }).error === "string" ? (data as { error: string }).error : `Erreur ${res.status}`;
      throw new DaemonError(message, res.status);
    }
    return data;
  } catch (err) {
    if (err instanceof DaemonError) throw err;
    throw new DaemonError("Démon Omnigroup injoignable : est-il lancé sur cette machine ?", 0);
  } finally {
    clearTimeout(timer);
  }
}

export class Daemon {
  constructor(
    readonly base: string,
    private readonly token: string | null,
  ) {}

  /** True when the daemon on the port knows our token (never sends the token itself). */
  async verify(): Promise<boolean> {
    if (!this.token) return false;
    const nonce = newNonce();
    const data = (await request(this.base, "GET", `/health?nonce=${nonce}`, null)) as { proofs?: unknown };
    return proves(data.proofs, this.token, nonce);
  }

  pairStart(): Promise<unknown> {
    return request(this.base, "POST", "/pair/start", null, {});
  }

  async pairFinish(code: string): Promise<string> {
    const data = (await request(this.base, "POST", "/pair/finish", null, { code, client_name: CLIENT_NAME })) as { token?: unknown };
    if (typeof data.token !== "string") throw new DaemonError("Réponse de couplage invalide.", 0);
    return data.token;
  }

  private call(method: string, path: string, body?: unknown): Promise<unknown> {
    return request(this.base, method, path, this.token, body);
  }

  providers(): Promise<unknown> {
    return this.call("GET", "/providers");
  }

  projects(): Promise<unknown> {
    return this.call("GET", "/projects");
  }

  async createChat(body: { text: string; provider: string; project?: string; page?: PagePayload }): Promise<string> {
    const data = (await this.call("POST", "/chats", body)) as { chat_id?: unknown };
    if (typeof data.chat_id !== "string") throw new DaemonError("Réponse du démon invalide.", 0);
    return data.chat_id;
  }

  sendChat(chatId: string, text: string): Promise<unknown> {
    return this.call("POST", `/chats/${encodeURIComponent(chatId)}/messages`, { text });
  }

  async getChat(chatId: string): Promise<ChatView> {
    return (await this.call("GET", `/chats/${encodeURIComponent(chatId)}`)) as ChatView;
  }
}
