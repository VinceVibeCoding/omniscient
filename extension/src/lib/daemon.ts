// The local Omnigroup daemon, as the extension sees it: pairing, and reporting the page. The token is only ever sent after
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

  /** The page in the browser, or that the person unticked it (PUT /browser/page). */
  reportPage(body: { page: PagePayload } | { excluded: true; url: string; title: string }): Promise<unknown> {
    return this.call("PUT", "/browser/page", body);
  }
}
