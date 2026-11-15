// Service worker: opens the side panel from the toolbar icon, keeps the failed requests of
// allowed sites (webRequest only reports sites we hold a permission for), registers the
// console-error collector on allowed sites, and shows « ON » on tabs whose site is shared.
import { originOf, pushCapped, stripQuery } from "./lib/util.js";

const CAPTURE_ID = "omnigroup-capture";
const LIST_MAX = 30;
// The string values Chrome expects (the typings model them as an enum).
const TYPES = ["main_frame", "sub_frame", "xmlhttprequest", "script", "stylesheet"] as unknown as chrome.webRequest.ResourceType[];
const MAIN_FRAME = ["main_frame"] as unknown as chrome.webRequest.ResourceType[];
const FILTER: chrome.webRequest.RequestFilter = { urls: ["http://*/*", "https://*/*"], types: TYPES };

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err: unknown) => console.warn("omnigroup: side panel", err));

async function record(tabId: number, item: { method: string; url: string; status: number }): Promise<void> {
  if (tabId < 0 || originOf(item.url)?.startsWith("http://127.0.0.1")) return;
  const key = `net:${tabId}`;
  const current = (await chrome.storage.session.get(key))[key];
  const list = Array.isArray(current) ? current : [];
  await chrome.storage.session.set({ [key]: pushCapped(list, { ...item, url: stripQuery(item.url) }, LIST_MAX) });
}

chrome.webRequest.onBeforeRequest.addListener(
  (d) => {
    if ((d.type as string) === "main_frame" && d.tabId >= 0) void chrome.storage.session.remove(`net:${d.tabId}`); // a new page
    return undefined;
  },
  { urls: ["http://*/*", "https://*/*"], types: MAIN_FRAME },
);
chrome.webRequest.onCompleted.addListener((d) => {
  if (d.statusCode >= 400) void record(d.tabId, { method: d.method, url: d.url, status: d.statusCode });
}, FILTER);
chrome.webRequest.onErrorOccurred.addListener((d) => {
  if (d.error !== "net::ERR_ABORTED") void record(d.tabId, { method: d.method, url: d.url, status: 0 });
}, FILTER);
chrome.tabs.onRemoved.addListener((tabId) => void chrome.storage.session.remove(`net:${tabId}`));

/** The sites the person allowed (the daemon's own address is not a site). */
async function allowedPatterns(): Promise<string[]> {
  const { origins = [] } = await chrome.permissions.getAll();
  return origins.filter((o) => !o.startsWith("http://127.0.0.1"));
}

async function syncCapture(): Promise<void> {
  await chrome.scripting.unregisterContentScripts({ ids: [CAPTURE_ID] }).catch(() => undefined);
  const matches = await allowedPatterns();
  if (matches.length === 0) return;
  await chrome.scripting.registerContentScripts([
    { id: CAPTURE_ID, js: ["capture-main.js"], matches, runAt: "document_start", world: "MAIN", persistAcrossSessions: true },
  ]);
}

async function badge(tabId: number, url: string | undefined): Promise<void> {
  const origin = originOf(url);
  const on = origin ? await chrome.permissions.contains({ origins: [`${origin}/*`] }) : false;
  await chrome.action.setBadgeText({ tabId, text: on ? "ON" : "" });
  if (on) await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f9d6b" });
}

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId).then((tab) => badge(tabId, tab.url)).catch(() => undefined);
});
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" || info.url) void badge(tabId, tab.url);
});
const refresh = (): void => {
  void syncCapture().catch((err: unknown) => console.warn("omnigroup: capture scripts", err));
  chrome.tabs.query({ active: true }).then((tabs) => tabs.forEach((t) => t.id !== undefined && void badge(t.id, t.url))).catch(() => undefined);
};
chrome.permissions.onAdded.addListener(refresh);
chrome.permissions.onRemoved.addListener(refresh);
chrome.runtime.onInstalled.addListener(refresh);
chrome.runtime.onStartup.addListener(refresh);
