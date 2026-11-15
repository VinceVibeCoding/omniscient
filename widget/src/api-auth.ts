// Typed wrappers for the account commands. The password goes out (sign in / sign up) and
// never comes back; the status only says who is signed in.
import { invoke } from "@tauri-apps/api/core";
import type { AuthProvider, AuthStatus, AuthUser } from "./types";

const PROVIDERS: readonly AuthProvider[] = ["google", "github"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");

export const SIGNED_OUT: AuthStatus = { configured: false, host: "", signed_in: false, user: null, pending: false, providers: [], message: "" };

export function toAuthStatus(raw: unknown): AuthStatus {
  if (!isRecord(raw)) return SIGNED_OUT;
  const u = raw.user;
  const user: AuthUser | null = isRecord(u) && text(u.email) !== "" ? { email: text(u.email), name: text(u.name), provider: text(u.provider) || "email" } : null;
  const providers = Array.isArray(raw.providers) ? raw.providers.filter((p): p is AuthProvider => PROVIDERS.includes(p as AuthProvider)) : [];
  return {
    configured: raw.configured === true,
    host: text(raw.host),
    signed_in: raw.signed_in === true && user !== null,
    user,
    pending: raw.pending === true,
    providers,
    message: text(raw.message),
  };
}

export async function authStatus(): Promise<AuthStatus> {
  return toAuthStatus(await invoke<unknown>("auth_status"));
}

/** Opens the browser on the provider's sign-in page; the result arrives as an `auth` event. */
export async function authStart(provider: AuthProvider): Promise<string> {
  const res = await invoke<unknown>("auth_start", { provider });
  return isRecord(res) ? text(res.url) : "";
}

export async function authPassword(mode: "signin" | "signup", email: string, password: string): Promise<AuthStatus> {
  return toAuthStatus(await invoke<unknown>("auth_password", { mode, email, password }));
}

export async function authSignout(): Promise<AuthStatus> {
  return toAuthStatus(await invoke<unknown>("auth_signout"));
}
