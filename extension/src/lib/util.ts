// Small pure helpers (unit-tested in test/util.test.ts).

export const DAEMON_DEFAULT = "http://127.0.0.1:7341";
const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

/** "https://shop.example" for a page we may read (http/https only), else null. */
export function originOf(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : null;
  } catch {
    return null;
  }
}

/** The extension holds a permission on 127.0.0.1 to reach the daemon: pages served there
 * would look "allowed" without the person ever agreeing, so they are never shared (a local
 * page can still be shared on http://localhost:<port>, with consent). */
export function shareableOrigin(url: string | undefined): string | null {
  const origin = originOf(url);
  if (!origin) return null;
  const host = new URL(origin).hostname;
  return host === "127.0.0.1" || host === "[::1]" ? null : origin;
}

/** The tab the panel is about: the active one, never a page of the extension itself. */
export function pickTab<T extends { url?: string }>(tabs: readonly T[], selfOrigin: string): T | null {
  return tabs.find((t) => !t.url?.startsWith(selfOrigin)) ?? null;
}

/** The host-permission pattern of an origin. */
export function originPattern(origin: string): string {
  return `${origin}/*`;
}

/** Scheme + host + path: query strings and fragments often carry tokens. */
export function stripQuery(url: string): string {
  try {
    const u = new URL(url);
    return `${u.origin}${u.pathname}`;
  } catch {
    return "";
  }
}

export function clip(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max);
}

/** A new list with `item` appended, keeping only the last `max` entries. */
export function pushCapped<T>(list: readonly T[], item: T, max: number): T[] {
  return [...list, item].slice(-max);
}

/** The daemon address: http on the machine itself only, any port, no path. */
export function validDaemonUrl(raw: string): string | null {
  try {
    const u = new URL(raw.trim());
    if (u.protocol !== "http:" || !LOOPBACK.has(u.hostname) || u.username || u.password || u.search || (u.pathname !== "/" && u.pathname !== "")) {
      return null;
    }
    return `${u.protocol}//${u.host}`;
  } catch {
    return null;
  }
}

export function hex(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return Array.from(view, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Equality that does not stop at the first different character. */
export function constantTimeEq(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
