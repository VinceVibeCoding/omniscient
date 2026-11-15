// Typed wrappers for the provider commands. The API key goes out (save) and never comes
// back: the daemon only reports "has a key" and its last 4 characters.
import { invoke } from "@tauri-apps/api/core";
import type { Provider, ProviderKind, ProviderList } from "./types";

const KINDS: readonly ProviderKind[] = ["claude-code", "openai", "gemini", "anthropic", "openai-compatible"];

export interface ProviderPatch {
  kind?: Exclude<ProviderKind, "claude-code">;
  label?: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  default?: boolean;
}

export interface ProviderTest {
  ok: boolean;
  models: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toProvider(raw: unknown): Provider | null {
  if (!isRecord(raw) || typeof raw.id !== "string" || !KINDS.includes(raw.kind as ProviderKind)) return null;
  const text = (v: unknown): string => (typeof v === "string" ? v : "");
  return {
    id: raw.id,
    kind: raw.kind as ProviderKind,
    label: text(raw.label) || raw.id,
    base_url: text(raw.base_url),
    model: text(raw.model),
    builtin: raw.builtin === true,
    has_key: raw.has_key === true,
    key_hint: text(raw.key_hint).slice(-4),
  };
}

export function toProviderList(raw: unknown): ProviderList {
  const items = isRecord(raw) && Array.isArray(raw.providers) ? raw.providers : [];
  const providers = items.map(toProvider).filter((p): p is Provider => p !== null);
  if (!providers.some((p) => p.id === "claude-code")) {
    providers.unshift({ id: "claude-code", kind: "claude-code", label: "Claude Code", base_url: "", model: "", builtin: true, has_key: false, key_hint: "" });
  }
  const wanted = isRecord(raw) && typeof raw.default === "string" ? raw.default : "claude-code";
  return { providers, default: providers.some((p) => p.id === wanted) ? wanted : "claude-code" };
}

export async function listProviders(): Promise<ProviderList> {
  return toProviderList(await invoke<unknown>("providers_list"));
}

export async function saveProvider(id: string, patch: ProviderPatch): Promise<ProviderList> {
  return toProviderList(await invoke<unknown>("provider_save", { id, patch }));
}

export async function removeProvider(id: string): Promise<ProviderList> {
  return toProviderList(await invoke<unknown>("provider_remove", { id }));
}

export async function testProvider(id: string): Promise<ProviderTest> {
  const res = await invoke<unknown>("provider_test", { id });
  const models = isRecord(res) && Array.isArray(res.models) ? res.models.filter((m): m is string => typeof m === "string") : [];
  return { ok: isRecord(res) && res.ok === true, models: models.slice(0, 80) };
}

export function finishWizard(): Promise<void> {
  return invoke("finish_wizard");
}
