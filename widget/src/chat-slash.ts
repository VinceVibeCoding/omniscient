// What a slash command does in the chat: the built-ins, a command (expanded by the daemon
// into the person's own message) or the start of a workflow. The host is the chat
// controller: this module never talks to the AI or the DOM itself.
import { errorText } from "./api";
import type { Expanded, ExtensionsView, ExtWorkflow } from "./api-ext";
import { listNote, reloadNote, type SlashCall } from "./ext-logic";

export interface SlashHost {
  extensions(): ExtensionsView;
  reload(): Promise<ExtensionsView | null>;
  expand(command: string, args: string): Promise<Expanded>;
  note(text: string): void;
  hasProject(): boolean;
  /** Sends `text` through the normal path; `attachPage` ticks the page box for this message. */
  sendExpanded(text: string, attachPage: boolean): Promise<void>;
  startWorkflow(workflow: ExtWorkflow): void;
}

function findWorkflow(view: ExtensionsView, name: string): ExtWorkflow | undefined {
  for (const ext of view.extensions) {
    if (!ext.enabled) continue;
    const found = ext.workflows.find((w) => w.name === name);
    if (found) return found;
  }
  return undefined;
}

/** Drops the transport prefix « Le démon a répondu 400 Bad Request. » to keep the French reason. */
export function reasonOf(message: string): string {
  const reason = message.replace(/^Le démon a répondu \d{3}[^.]*\.\s*/, "").trim();
  return reason || message;
}

async function runCommand(call: SlashCall, host: SlashHost): Promise<void> {
  let expanded: Expanded;
  try {
    expanded = await host.expand(call.name, call.args);
  } catch (err) {
    host.note(reasonOf(errorText(err))); // the daemon's own French message: nothing is sent
    return;
  }
  await host.sendExpanded(expanded.text, expanded.attachPage);
}

export async function runSlash(call: SlashCall, host: SlashHost): Promise<void> {
  if (call.name === "reload") {
    const view = await host.reload();
    if (view) host.note(reloadNote(view));
    return;
  }
  if (call.name === "extensions") {
    host.note(listNote(host.extensions()));
    return;
  }
  const workflow = findWorkflow(host.extensions(), call.name);
  if (!workflow) return runCommand(call, host);
  if (workflow.needsProject && !host.hasProject()) {
    host.note(`Le workflow /${workflow.name} a besoin d'un projet : choisissez-en un, puis recommencez.`);
    return;
  }
  host.startWorkflow(workflow);
}
