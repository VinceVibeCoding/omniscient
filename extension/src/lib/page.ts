// Reading the page the person is on, only for a site they allowed. Functions passed to
// chrome.scripting.executeScript run inside the page, so they must be self-contained.
import { shareableOrigin, stripQuery } from "./util.js";
import type { PagePayload } from "./daemon.js";

const TEXT_MAX = 20_000;
const SELECTION_MAX = 4_000;
const LIST_MAX = 30;

/** Runs in the page (isolated world): visible text, selection, title. Field values (and so
 * passwords) are not part of innerText. */
function readVisible(): { url: string; title: string; text: string; selection: string } {
  const text = (document.body?.innerText ?? "").replace(/\n{3,}/g, "\n\n");
  return { url: location.href, title: document.title, text: text.slice(0, 20_000), selection: String(window.getSelection() ?? "").slice(0, 4_000) };
}

/** Runs in the page (main world): the console errors capture-main.js collected. */
function readErrors(): string[] {
  const list = (window as unknown as { __omnigroupErrors?: unknown }).__omnigroupErrors;
  return Array.isArray(list) ? list.filter((e): e is string => typeof e === "string").slice(-30) : [];
}

export async function isAllowed(origin: string | null): Promise<boolean> {
  return origin ? chrome.permissions.contains({ origins: [`${origin}/*`] }) : false;
}

/** Everything about the tab, or an error message when the site is not allowed. */
export async function capturePage(tab: chrome.tabs.Tab): Promise<PagePayload> {
  const origin = shareableOrigin(tab.url);
  if (tab.id === undefined || !(await isAllowed(origin))) throw new Error("Ce site n'est pas autorisé : autorisez-le d'abord.");
  const target = { tabId: tab.id };
  const [visible] = await chrome.scripting.executeScript({ target, func: readVisible });
  const [errors] = await chrome.scripting.executeScript({ target, func: readErrors, world: "MAIN" }).catch(() => [{ result: [] as string[] }]);
  const key = `net:${tab.id}`;
  const stored = (await chrome.storage.session.get(key))[key];
  const page = visible?.result;
  if (!page) throw new Error("Impossible de lire cette page.");
  return {
    url: stripQuery(page.url),
    title: page.title.slice(0, 300),
    text: page.text.slice(0, TEXT_MAX),
    selection: page.selection.slice(0, SELECTION_MAX),
    errors: (errors?.result ?? []).slice(-LIST_MAX),
    network: Array.isArray(stored) ? stored.slice(-LIST_MAX) : [],
  };
}
