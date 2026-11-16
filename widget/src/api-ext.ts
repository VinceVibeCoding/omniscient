// Typed wrappers for the extension commands. The daemon's JSON is untrusted: every shape
// is normalised here and an unknown one becomes a safe default (nothing throws on a
// malformed reply, except `expandCommand`, which has nothing to send without a text).
import { invoke } from "@tauri-apps/api/core";

export type PresetKind = "openai" | "gemini" | "anthropic" | "openai-compatible";
const PRESET_KINDS: readonly PresetKind[] = ["openai", "gemini", "anthropic", "openai-compatible"];

export interface ExtCommand {
  name: string;
  title: string;
  args: readonly { name: string; default: string | null }[];
  attachPage: boolean;
}
export interface ExtTheme {
  id: string;
  label: string;
  colors: Readonly<Record<string, string>>;
}
export interface ExtWorkflow {
  name: string;
  title: string;
  needsProject: boolean;
  steps: readonly string[];
}
export interface ExtPreset {
  id: string;
  label: string;
  kind: PresetKind;
  base_url: string;
  model: string;
}
export interface Extension {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  enabled: boolean;
  commands: readonly ExtCommand[];
  themes: readonly ExtTheme[];
  workflows: readonly ExtWorkflow[];
  presets: readonly ExtPreset[];
}
export interface ExtLoadError {
  id: string;
  message: string;
}
export interface ExtensionsView {
  extensions: readonly Extension[];
  errors: readonly ExtLoadError[];
}
export interface Expanded {
  text: string;
  attachPage: boolean;
}

export const EMPTY_EXTENSIONS: ExtensionsView = { extensions: [], errors: [] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const items = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

function each<T>(raw: unknown, parse: (item: Record<string, unknown>) => T | null): T[] {
  return items(raw)
    .map((item) => (isRecord(item) ? parse(item) : null))
    .filter((item): item is T => item !== null);
}

function toCommand(raw: Record<string, unknown>): ExtCommand | null {
  if (!str(raw.name)) return null;
  const args = each(raw.args, (a) => (str(a.name) ? { name: str(a.name), default: typeof a.default === "string" ? a.default : null } : null));
  return { name: str(raw.name), title: str(raw.title) || str(raw.name), args, attachPage: raw.attach_page === true };
}

function toTheme(raw: Record<string, unknown>): ExtTheme | null {
  if (!str(raw.id) || !isRecord(raw.colors)) return null;
  const colors: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw.colors)) if (typeof value === "string") colors[key] = value;
  return { id: str(raw.id), label: str(raw.label) || str(raw.id), colors };
}

function toWorkflow(raw: Record<string, unknown>): ExtWorkflow | null {
  if (!str(raw.name)) return null;
  const steps = each(raw.steps, (s) => (str(s.prompt) ? str(s.prompt) : null));
  return { name: str(raw.name), title: str(raw.title) || str(raw.name), needsProject: raw.needs_project === true, steps };
}

function toPreset(raw: Record<string, unknown>): ExtPreset | null {
  const kind = PRESET_KINDS.find((k) => k === raw.kind);
  if (!str(raw.id) || !kind) return null;
  return { id: str(raw.id), label: str(raw.label) || str(raw.id), kind, base_url: str(raw.base_url), model: str(raw.model) };
}

function toExtension(raw: Record<string, unknown>): Extension | null {
  if (!str(raw.id)) return null;
  return {
    id: str(raw.id),
    name: str(raw.name) || str(raw.id),
    description: str(raw.description),
    version: str(raw.version),
    author: str(raw.author),
    enabled: raw.enabled !== false,
    commands: each(raw.commands, toCommand),
    themes: each(raw.themes, toTheme),
    workflows: each(raw.workflows, toWorkflow),
    presets: each(raw.provider_presets, toPreset),
  };
}

export function toExtensionsView(raw: unknown): ExtensionsView {
  if (!isRecord(raw)) return EMPTY_EXTENSIONS;
  return {
    extensions: each(raw.extensions, toExtension),
    errors: each(raw.errors, (e) => (str(e.message) ? { id: str(e.id), message: str(e.message) } : null)),
  };
}

export async function listExtensions(): Promise<ExtensionsView> {
  return toExtensionsView(await invoke<unknown>("ext_list"));
}

export async function reloadExtensions(): Promise<ExtensionsView> {
  return toExtensionsView(await invoke<unknown>("ext_reload"));
}

export async function setExtensionEnabled(id: string, enabled: boolean): Promise<ExtensionsView> {
  return toExtensionsView(await invoke<unknown>("ext_set_enabled", { id, enabled }));
}

export async function removeExtension(id: string): Promise<ExtensionsView> {
  return toExtensionsView(await invoke<unknown>("ext_remove", { id }));
}

/** The text a command produces (the person's own message) and whether it wants the page. */
export async function expandCommand(command: string, args: string): Promise<Expanded> {
  const res = await invoke<unknown>("ext_expand", { command, args });
  if (!isRecord(res) || str(res.text).trim() === "") throw new Error("Réponse du démon invalide.");
  return { text: str(res.text), attachPage: res.attach_page === true };
}
