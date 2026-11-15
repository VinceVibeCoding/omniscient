// Reading the page the person is on, only for a site they allowed. Functions passed to
// chrome.scripting.executeScript run inside the page, so they must be self-contained.
import { pageKey, shareableOrigin, stripQuery } from "./util.js";
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

/** True when the person unticked « Joindre cette page » for the page this tab is on. */
export async function isExcluded(tab: chrome.tabs.Tab | null): Promise<boolean> {
  if (tab?.id === undefined) return false;
  const key = `skip:${tab.id}`;
  return (await chrome.storage.session.get(key))[key] === pageKey(tab.url);
}

/** Untick / tick for this page only: a new page in the tab starts ticked again. */
export async function setExcluded(tab: chrome.tabs.Tab, excluded: boolean): Promise<void> {
  if (tab.id === undefined) return;
  const key = `skip:${tab.id}`;
  if (excluded) await chrome.storage.session.set({ [key]: pageKey(tab.url) });
  else await chrome.storage.session.remove(key);
}

/** Everything about the tab (only called when the person sends with the box ticked). */
export async function capturePage(tab: chrome.tabs.Tab, daemonBase: string): Promise<PagePayload> {
  if (tab.id === undefined || !shareableOrigin(tab.url, daemonBase)) throw new Error("Cette page ne peut pas être jointe.");
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
