// Pure logic of the extensions in the widget (no DOM, no Tauri): slash parsing and
// filtering, theme colour validation, workflow sequencing, summaries. Kept separate so
// it can be tested with `node --test`.
import type { ExtensionsView } from "./api-ext";
import type { ChatMessage } from "./types";

// ---- slash commands ----------------------------------------------------------------

export type SlashKind = "builtin" | "command" | "workflow";

export interface SlashEntry {
  name: string;
  title: string;
  kind: SlashKind;
}

export const BUILTIN_ENTRIES: readonly SlashEntry[] = [
  { name: "reload", title: "Recharger les extensions", kind: "builtin" },
  { name: "extensions", title: "Lister les extensions chargées", kind: "builtin" },
];

const COMMAND_NAME = /^[a-z][a-z0-9-]{0,29}$/;
const PARTIAL_NAME = /^\/([a-z0-9-]{0,30})$/;
const SUGGESTIONS_MAX = 8;

/** Built-ins, then every command and workflow of each enabled extension. */
export function buildEntries(view: ExtensionsView): SlashEntry[] {
  const entries: SlashEntry[] = [...BUILTIN_ENTRIES];
  for (const ext of view.extensions) {
    if (!ext.enabled) continue;
    for (const c of ext.commands) entries.push({ name: c.name, title: c.title, kind: "command" });
    for (const w of ext.workflows) entries.push({ name: w.name, title: w.title, kind: "workflow" });
  }
  return entries;
}

/** The name being typed when the text is just « /par » (no space yet), else null. */
export function slashQuery(text: string): string | null {
  const match = PARTIAL_NAME.exec(text);
  return match ? (match[1] ?? "") : null;
}

/** Entries whose name starts with the query first, then those that contain it. */
export function filterEntries(entries: readonly SlashEntry[], query: string, limit = SUGGESTIONS_MAX): SlashEntry[] {
  const q = query.toLowerCase();
  const starts = entries.filter((e) => e.name.startsWith(q));
  const contains = entries.filter((e) => !e.name.startsWith(q) && (e.name.includes(q) || e.title.toLowerCase().includes(q)));
  return [...starts, ...contains].slice(0, limit);
}

export interface SlashCall {
  name: string;
  args: string;
}

/** « /resume 7 » -> {name: "resume", args: "7"}; null when it is not a slash command. */
export function parseSlash(text: string): SlashCall | null {
  const match = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(text.trim());
  if (!match || !COMMAND_NAME.test(match[1] ?? "")) return null;
  return { name: match[1] ?? "", args: (match[2] ?? "").trim() };
}

/** The text a pick puts in the box: the name and a space, ready for arguments. */
export function completion(entry: SlashEntry): string {
  return `/${entry.name} `;
}

// ---- theme colours (same rules as the daemon, checked again here) --------------------

export const THEME_PROPERTIES: readonly string[] = [
  "--accent",
  "--background",
  "--border",
  "--error",
  "--foreground",
  "--muted",
  "--primary",
  "--raised",
  "--ring",
  "--secondary",
  "--success",
  "--surface",
  "--warning",
];

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const RGB_COLOR = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*(0|1|0?\.\d{1,3}|1\.0{1,3})\s*)?\)$/;
const CHANNEL_MAX = 255;

export function isThemeColor(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (HEX_COLOR.test(value)) return true;
  const rgb = RGB_COLOR.exec(value);
  return rgb !== null && [rgb[1], rgb[2], rgb[3]].every((c) => Number(c) <= CHANNEL_MAX);
}

/** Only allowlisted properties with valid colours; everything else is dropped. */
export function safeThemeColors(colors: Readonly<Record<string, unknown>>): [string, string][] {
  const out: [string, string][] = [];
  for (const prop of THEME_PROPERTIES) {
    const value = Object.hasOwn(colors, prop) ? colors[prop] : undefined;
    if (isThemeColor(value)) out.push([prop, value]);
  }
  return out;
}

// ---- workflows ----------------------------------------------------------------------

export interface WorkflowRun {
  name: string;
  steps: readonly string[];
  /** Index of the step to send next. */
  next: number;
  /** A turn of this run is in progress: the next idle/error ends it. */
  awaiting: boolean;
}

export function startRun(name: string, steps: readonly string[]): WorkflowRun {
  return { name, steps, next: 0, awaiting: false };
}

export type RunStep =
  | { kind: "send"; prompt: string; index: number; total: number; run: WorkflowRun }
  | { kind: "done" };

/** The step to send now, or "done" once all have been sent. */
export function nextStep(run: WorkflowRun): RunStep {
  const prompt = run.steps[run.next];
  if (prompt === undefined) return { kind: "done" };
  return { kind: "send", prompt, index: run.next + 1, total: run.steps.length, run: { ...run, next: run.next + 1, awaiting: true } };
}

export type TurnEnd = { kind: "ignore" } | { kind: "stop" } | { kind: "advance"; run: WorkflowRun };

/** What a chat state event means for the run: only the end of the awaited turn counts. */
export function onChatState(run: WorkflowRun, state: string): TurnEnd {
  if (!run.awaiting || (state !== "idle" && state !== "error")) return { kind: "ignore" };
  if (state === "error") return { kind: "stop" };
  return { kind: "advance", run: { ...run, awaiting: false } };
}

// ---- notes --------------------------------------------------------------------------

const plural = (n: number, one: string, many: string): string => `${n} ${n > 1 ? many : one}`;

export function reloadNote(view: ExtensionsView): string {
  const enabled = view.extensions.filter((e) => e.enabled);
  const count = (pick: (e: ExtensionsView["extensions"][number]) => number): number => enabled.reduce((n, e) => n + pick(e), 0);
  const commands = count((e) => e.commands.length + e.workflows.length);
  const themes = count((e) => e.themes.length);
  const presets = count((e) => e.presets.length);
  const errors = view.errors.length;
  const head = `Extensions rechargées : ${plural(commands, "commande", "commandes")}, ${plural(themes, "thème", "thèmes")}, ${plural(presets, "préréglage", "préréglages")} (${plural(errors, "erreur", "erreurs")})`;
  return [head, ...view.errors.map((e) => `• ${e.id ? `${e.id} : ` : ""}${e.message}`)].join("\n");
}

export function listNote(view: ExtensionsView): string {
  if (view.extensions.length === 0 && view.errors.length === 0) return "Aucune extension installée.";
  const lines = view.extensions.map((e) => {
    const state = e.enabled ? "" : " (désactivée)";
    return `• ${e.name} ${e.version}${state} : ${plural(e.commands.length, "commande", "commandes")}, ${plural(e.workflows.length, "workflow", "workflows")}, ${plural(e.themes.length, "thème", "thèmes")}`;
  });
  const errors = view.errors.map((e) => `• erreur ${e.id ? `${e.id} : ` : ""}${e.message}`);
  return ["Extensions chargées :", ...lines, ...errors].join("\n");
}

/** The conversation with the local notes slotted in by time (notes are never stored). */
export function mergeNotes(messages: readonly ChatMessage[], notes: readonly ChatMessage[]): readonly ChatMessage[] {
  if (notes.length === 0) return messages;
  const out = [...messages];
  for (const note of notes) {
    const at = Date.parse(note.at);
    const index = out.findIndex((m) => Date.parse(m.at) > at);
    if (index < 0) out.push(note);
    else out.splice(index, 0, note);
  }
  return out;
}
